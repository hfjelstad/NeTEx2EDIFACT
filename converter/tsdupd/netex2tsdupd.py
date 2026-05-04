# -*- coding: utf-8 -*-
"""
netex2tsdupd.py
~~~~~~~~~~~~~~~
Convert a trimmed NeTEx SiteFrame XML (NSR rail stations) directly to a
TSDUPD EDIFACT file, bypassing the CSV intermediate step.

Uses MERITS RowsInMemory to feed dataclass instances straight into the
CsvsToEdifact converter.

Usage:
  python netex2tsdupd.py [--input <xml>] [--output <.r file>] [--originator <code>]

Defaults:
  --input      ../Nordic source material/tiamat-export-RailStations-202604262300285592.trimmed.uic9.xml
  --output     ./NEW_TSDUPD/new_TSDUPD.r
  --originator (derived from <ParticipantRef> in the NeTEx file via PARTICIPANT_TO_RICS)
"""

from __future__ import annotations

import argparse
import time
import xml.etree.ElementTree as ET
import zipfile
from datetime import date, datetime
from pathlib import Path
from typing import List

from merits.tsdupd.csv_model import Footpath, Mct, Meta, Stop, Synonym
from merits.tsdupd.csvs_to_edifact import CsvsToEdifact
from merits.tsdupd import definition

from converter.shared.edifact_mappings import (
    country_from_uic,
    resolve_originator,
    timezone_for_country,
    to_ascii,
)
from converter.shared.netex_helpers import (
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


# ---------------------------------------------------------------------------
# EDIFACT-specific helpers (only what is unique to TSDUPD lives here)
# ---------------------------------------------------------------------------

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

def convert(xml_path: Path, output_file: Path, originator: str | None) -> None:
    tree = ET.parse(xml_path)
    root = tree.getroot()
    participant = participant_ref(root)
    resolved_originator = resolve_originator(participant, originator)
    print(f"ParticipantRef={participant!r} -> originator (RICS) {resolved_originator!r}")
    stop_places = root.findall(f".//{{{NS}}}StopPlace")
    print(f"Found {len(stop_places)} StopPlaces in {xml_path.name}")
    uic_to_mct = build_uic_to_mct(root)
    if uic_to_mct:
        print(f"Found {len(uic_to_mct)} SiteConnection self-loops with MCT values")

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
            function_code="29",  # UN/EDIFACT 3227: '29' = station / place of departure/arrival
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

    # Clean and recreate the output directory so reruns don't keep stale files.
    output_dir = output_file.parent
    if output_dir.exists():
        for child in output_dir.iterdir():
            if child.is_file():
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
        description="Convert trimmed NeTEx SiteFrame directly to TSDUPD EDIFACT.",
    )
    parser.add_argument(
        "--input",
        default="../Nordic source material/tiamat-export-RailStations-202604262300285592.trimmed.uic9.xml",
    )
    parser.add_argument(
        "--output",
        default="./NEW_TSDUPD/new_TSDUPD.r",
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
        xml_path=Path(args.input),
        output_file=Path(args.output),
        originator=args.originator,
    )


if __name__ == "__main__":
    main()
