# -*- coding: utf-8 -*-
"""
netex2tsdupd.py
~~~~~~~~~~~~~~~
Convert a NeTEx SiteFrame directly to a TSDUPD EDIFACT
file, bypassing the CSV intermediate step.

Uses MERITS RowsInMemory to feed dataclass instances straight into the
CsvsToEdifact converter.

Usage:
  python netex2tsdupd.py [--input-dir <folder>] [--output <.r file>] [--originator <code>]

Defaults:
  --input-dir  ../../Source/TSDUPD          (scans for newest *.zip or *.xml)
  --output     ./NEW_TSDUPD/new_TSDUPD.r
  --originator (derived from <ParticipantRef> in the NeTEx file via PARTICIPANT_TO_RICS)

Drop a NeTEx station export (*.zip or *.xml) into the input folder and run
without arguments. MCT values are read from
Configuration/merits_mct_lookup.csv when present.
"""

from __future__ import annotations

import sys
from pathlib import Path
# Ensure the project root is on sys.path when this script is run directly
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import argparse
import csv
import io
import time
import xml.etree.ElementTree as ET
import zipfile
from datetime import date, datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from merits.tsdupd.csv_model import Footpath, Mct, Meta, Stop, Synonym
from merits.tsdupd.csvs_to_edifact import CsvsToEdifact
from merits.tsdupd import definition

from Converter.Shared.edifact_mappings import (
    country_from_uic,
    resolve_originator,
    timezone_for_country,
    to_ascii,
)
from Converter.Shared.netex_helpers import (
    NS,
    alt_names,
    build_uic_to_mct,
    coordinates,
    participant_ref,
    reservation_code,
    rows_in_memory,
    text as netex_text,
    uic_code,
    validity,
)

# Configuration/ is three levels up from converter/tsdupd/
_CONF_DIR = Path(__file__).resolve().parent.parent.parent / "Configuration"
_MCT_CSV  = _CONF_DIR / "merits_mct_lookup.csv"


# ---------------------------------------------------------------------------
# Input resolution helpers
# ---------------------------------------------------------------------------

def _find_newest(input_dir: Path, *patterns: str) -> Optional[Path]:
    """Return the newest file in *input_dir* matching any of *patterns*, or None."""
    candidates = [p for pat in patterns for p in input_dir.glob(pat) if p.is_file()]
    if not candidates:
        return None
    return max(candidates, key=lambda p: p.stat().st_mtime)


def _load_xml(source: Path) -> Tuple[ET.ElementTree, str]:
    """Parse NeTEx XML from *source* (plain XML or zip containing one XML).

    Returns ``(ElementTree, display_name)``.
    """
    if source.suffix.lower() == ".zip":
        with zipfile.ZipFile(source) as zf:
            xml_names = [n for n in zf.namelist() if n.lower().endswith(".xml")]
            if not xml_names:
                raise FileNotFoundError(f"No XML file found inside {source.name}")
            xml_name = xml_names[0]
            with zf.open(xml_name) as fh:
                return ET.parse(io.BytesIO(fh.read())), f"{source.name}/{xml_name}"
    return ET.parse(source), source.name


def _load_mct_csv(csv_path: Path) -> Dict[str, int]:
    """Load ``{uic_code: minutes}`` from a ``;``-delimited CSV with headers
    ``uic_code;mct_minutes``. Rows with missing/invalid data are skipped.
    """
    out: Dict[str, int] = {}
    with csv_path.open(encoding="utf-8", newline="") as fh:
        for row in csv.DictReader(fh, delimiter=";"):
            uic = (row.get("uic_code") or "").strip()
            try:
                minutes = int((row.get("mct_minutes") or "").strip())
            except ValueError:
                continue
            if uic and minutes > 0:
                out[uic] = minutes
    return out


# ---------------------------------------------------------------------------
# EDIFACT-specific helpers (only what is unique to TSDUPD lives here)
# ---------------------------------------------------------------------------

# UN/EDIFACT code list 3227 — location function qualifier
_MODE_TO_FUNCTION_CODE: Dict[str, str] = {
    "rail":      "29",  # Station/terminal
    "metro":     "29",
    "tram":      "29",
    "water":     "50",  # Port/ferry terminal
    "bus":       "21",  # Bus station
    "coach":     "21",
    "telecabin": "29",
    "funicular": "29",
}
_DEFAULT_FUNCTION_CODE = "29"


def _location_function_code(stop_place: ET.Element) -> str:
    """Map NeTEx TransportMode to UN/EDIFACT 3227 location function code."""
    mode = (stop_place.findtext(f"{{{NS}}}TransportMode") or "").strip().lower()
    return _MODE_TO_FUNCTION_CODE.get(mode, _DEFAULT_FUNCTION_CODE)

def _to_dms(value: str, hemispheres: tuple, width: int) -> str:
    """Convert a decimal-degree string to EDIFACT DMS form '[D]DDMMSS<H>'.

    UIC TSDUPD ALS/6000 latitude is 6 digits + N/S (DDMMSS), longitude
    is 7 digits + E/W (DDDMMSS). Returns '' if value is empty/invalid.
    """
    if not value:
        return ""
    try:
        deg = float(value)
    except ValueError:
        return ""
    hemi = hemispheres[0] if deg >= 0 else hemispheres[1]
    deg = abs(deg)
    d = int(deg)
    m_full = (deg - d) * 60
    m = int(m_full)
    s = int(round((m_full - m) * 60))
    if s == 60:
        s = 0
        m += 1
    if m == 60:
        m = 0
        d += 1
    return f"{d:0{width}d}{m:02d}{s:02d}{hemi}"


# ---------------------------------------------------------------------------
# Conversion
# ---------------------------------------------------------------------------

def convert(input_dir: Path, output_file: Path, originator: str | None,
            *, input_file: Path | None = None) -> None:
    if input_file is not None:
        source = input_file
    else:
        source = _find_newest(input_dir, "*.zip", "*.xml")
    if source is None:
        raise FileNotFoundError(
            f"No *.zip or *.xml found in {input_dir}. "
            "Drop a NeTEx export there and try again."
        )

    tree, display_name = _load_xml(source)
    root = tree.getroot()
    participant = participant_ref(root)
    resolved_originator = resolve_originator(participant, originator)
    print(f"Input:          {source}")
    print(f"ParticipantRef={participant!r} -> originator (RICS) {resolved_originator!r}")
    stop_places = root.findall(f".//{{{NS}}}StopPlace")
    print(f"Found {len(stop_places)} StopPlaces in {display_name}")

    if _MCT_CSV.exists():
        uic_to_mct = _load_mct_csv(_MCT_CSV)
        print(f"MCT: {len(uic_to_mct)} entries from {_MCT_CSV.name}")
    else:
        uic_to_mct = build_uic_to_mct(root)
        if uic_to_mct:
            print(f"MCT: {len(uic_to_mct)} SiteConnection self-loops")

    today = date.today().isoformat()
    # MERITS expects `reference` to be a timestamp '%Y-%m-%dT%H%M%S' (15 chars).
    # The HDR collector takes reference[:-2] as date_1 (YYYY-MM-DDThhmm, qualifier 45).
    reference = datetime.now().strftime("%Y-%m-%dT%H%M%S")
    meta_list = [Meta(
        reference=reference,
        validity_first_date=today,
        validity_last_date=None,
        originator=resolved_originator,
    )]

    stops: List[Stop] = []
    synonyms: List[Synonym] = []
    stop_id = 0
    synonym_id = 0

    for sp in stop_places:
        uic = uic_code(sp)
        if not uic:
            continue

        stop_id += 1
        name = netex_text(sp, "Name")
        lat, lon = coordinates(sp)
        valid_from, valid_to = validity(sp)
        country = country_from_uic(uic)
        tz_zone, tz_variation = timezone_for_country(country)

        stops.append(Stop(
            stop_id=stop_id,
            function_code=_location_function_code(sp),
            uic_code=uic,
            location_name=to_ascii(name),
            location_short_name=None,
            latitude=_to_dms(lat, ("N", "S"), 2) or None,
            longitude=_to_dms(lon, ("E", "W"), 3) or None,
            valid_from=valid_from or None,
            valid_to=valid_to or None,
            # POP+87 default transfer time uses EDIFACT period format HHMM
            # (data element 2380), e.g. 8 minutes -> '0008', 75 min -> '0115'.
            default_transfer_time=(
                f"{uic_to_mct[uic] // 60:02d}{uic_to_mct[uic] % 60:02d}"
                if uic in uic_to_mct else None
            ),
            country=country or None,
            timezone_1=tz_zone,
            timezone_2=tz_variation,
            reservation_code=reservation_code(sp) or None,
        ))

        for lang, alt_name in alt_names(sp):
            synonym_id += 1
            synonyms.append(Synonym(
                synonym_id=synonym_id,
                stop_id=stop_id,
                uic_code=uic,
                language=lang,
                synonym=to_ascii(alt_name),
            ))

    print(f"Converted {len(stops)} stops, {len(synonyms)} synonyms")

    converter = CsvsToEdifact()
    converter.load({
        definition.META_FILE_NAME:     rows_in_memory(meta_list, Meta),
        definition.STOP_FILE_NAME:     rows_in_memory(stops, Stop),
        definition.SYNONYM_FILE_NAME:  rows_in_memory(synonyms, Synonym),
        definition.MCT_FILE_NAME:      rows_in_memory([], Mct),
        definition.FOOTPATH_FILE_NAME: rows_in_memory([], Footpath),
    })
    edifact_text = converter.get()

    # Clean previous TSDUPD outputs in the directory so reruns don't keep
    # stale .zip archives. Other files (e.g. SKDUPD outputs written to the
    # same folder) are intentionally left alone.
    output_dir = output_file.parent
    if output_dir.exists():
        for child in output_dir.iterdir():
            if child.is_file() and (
                child.name == output_file.name
                or (child.name.startswith("TSDUPD_") and child.suffix == ".zip")
            ):
                child.unlink()
    output_dir.mkdir(parents=True, exist_ok=True)
    output_file.write_text(edifact_text, encoding="utf-8")
    print(f"Written TSDUPD EDIFACT to {output_file}")

    # Also produce a unix-timestamped .zip alongside the .r file. This matches
    # the historical MERITS submission convention (Legacy/zipper.py): a single
    # archive named "TSDUPD_<unix>.zip" containing the EDIFACT payload, ready
    # for SFTP upload to MERITS test/prod.
    unix_ts = int(time.time())
    zip_path = output_dir / f"TSDUPD_{unix_ts}.zip"
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.write(output_file, arcname=output_file.name)
    print(f"Written TSDUPD ZIP to {zip_path}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="netex2tsdupd",
        description="Convert NeTEx SiteFrame to TSDUPD EDIFACT.",
    )
    _root = Path(__file__).resolve().parent.parent.parent
    parser.add_argument(
        "--input-dir",
        default=str(_root / "Source" / "TSDUPD"),
        help="Folder containing the NeTEx export (*.zip or *.xml). Newest file is used.",
    )
    parser.add_argument(
        "--output",
        default=str(_root / "NEW_TSDUPD" / "new_TSDUPD.r"),
    )
    parser.add_argument(
        "--originator",
        default=None,
        help=(
            "Override the EDIFACT ORG/3036 originator (4-digit UIC/RICS company code). "
            "By default this is derived from <ParticipantRef> in the NeTEx file via "
            "PARTICIPANT_TO_RICS in this script."
        ),
    )
    return parser


def main() -> None:
    args = _build_arg_parser().parse_args()
    convert(
        input_dir=Path(args.input_dir),
        output_file=Path(args.output),
        originator=args.originator,
    )


if __name__ == "__main__":
    main()
