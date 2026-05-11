# -*- coding: utf-8 -*-
"""
netex2tsdupd_csv.py
~~~~~~~~~~~~~~~~~~~
Convert a NeTEx SiteFrame XML to the CSV files
expected by the MERITS TSDUPD converter (csv2TSDUPD.py).

Output files written to ./CSV/:
  meta.csv
  TSDUPD_STOP.csv
  TSDUPD_SYNONYM.csv   (AlternativeName entries, if any)

Usage:
  python netex2tsdupd_csv.py [--input <xml>] [--csv-dir <dir>] [--originator <code>]

Defaults:
  --input       (required)
  --csv-dir     ./CSV
  --originator  (derived from <ParticipantRef> in the NeTEx file via PARTICIPANT_TO_RICS)
"""

from __future__ import annotations

import argparse
import csv
import xml.etree.ElementTree as ET
from datetime import date, datetime
from pathlib import Path

from Converter.Shared.edifact_mappings import country_from_uic, resolve_originator
from Converter.Shared.netex_helpers import (
    NS,
    alt_names,
    build_uic_to_mct,
    coordinates,
    participant_ref,
    reservation_code,
    text as netex_text,
    uic_code,
    validity,
)


# ---------------------------------------------------------------------------
# Main conversion
# ---------------------------------------------------------------------------

def convert(xml_path: Path, csv_dir: Path, originator) -> None:
    csv_dir.mkdir(parents=True, exist_ok=True)

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

    # ---- meta.csv ----
    today = date.today().isoformat()
    # MERITS expects `reference` to be a timestamp '%Y-%m-%dT%H%M%S' (15 chars).
    reference = datetime.now().strftime("%Y-%m-%dT%H%M%S")
    with open(csv_dir / "meta.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(["reference", "validity_first_date", "validity_last_date", "originator"])
        w.writerow([reference, today, "", resolved_originator])

    # ---- TSDUPD_STOP.csv + TSDUPD_SYNONYM.csv ----
    stop_headers = [
        "stop_id", "function_code", "uic_code", "location_name",
        "location_short_name", "latitude", "longitude",
        "valid_from", "valid_to", "default_transfer_time",
        "country", "timezone_1", "timezone_2", "reservation_code",
    ]
    synonym_headers = [
        "synonym_id", "stop_id", "uic_code", "language", "synonym",
    ]

    stop_rows = []
    synonym_rows = []
    synonym_id = 1

    for stop_id, sp in enumerate(stop_places, start=1):
        uic = uic_code(sp)
        if not uic:
            # Skip stops without a UIC code – they are unusable in TSDUPD
            print(f"  SKIP {sp.get('id')} — no UIC code")
            continue

        name = netex_text(sp, "Name")
        lat, lon = coordinates(sp)
        valid_from, valid_to = validity(sp)
        country = country_from_uic(uic)
        res_code = reservation_code(sp)

        stop_rows.append([
            stop_id,
            "M",        # function_code: M = major station (default; adjust as needed)
            uic,
            name,
            "",         # location_short_name
            lat,
            lon,
            valid_from,
            valid_to,
            str(uic_to_mct.get(uic, "")),  # default_transfer_time — from SiteConnection self-loop
            country,
            "",         # timezone_1
            "",         # timezone_2
            res_code,
        ])

        for lang, alt_name in alt_names(sp):
            synonym_rows.append([synonym_id, stop_id, uic, lang, alt_name])
            synonym_id += 1

    with open(csv_dir / "TSDUPD_STOP.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(stop_headers)
        w.writerows(stop_rows)

    with open(csv_dir / "TSDUPD_SYNONYM.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(synonym_headers)
        w.writerows(synonym_rows)

    # MERITS requires these files to be present even when empty
    mct_headers = [
        "mct_id", "stop_id", "uic_code", "service_brand_1", "service_brand_2",
        "time", "service_provider_1", "service_provider_2",
    ]
    with open(csv_dir / "TSDUPD_MCT.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(mct_headers)

    footpath_headers = [
        "footpath_id", "stop_id", "uic_code_1", "uic_code_2", "duration",
        "duration_unit", "relationship_code_13", "footpath_6_or_hierarchy_14",
        "attributes_with_semicolon", "service_brand_1", "service_brand_2",
        "service_provider_1", "service_provider_2",
    ]
    with open(csv_dir / "TSDUPD_FOOTPATH.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(footpath_headers)

    print(f"Written {len(stop_rows)} stops to {csv_dir / 'TSDUPD_STOP.csv'}")
    print(f"Written {len(synonym_rows)} synonyms to {csv_dir / 'TSDUPD_SYNONYM.csv'}")
    print(f"Written empty TSDUPD_MCT.csv and TSDUPD_FOOTPATH.csv to {csv_dir}")
    print(f"Written meta.csv to {csv_dir / 'meta.csv'}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="netex2tsdupd_csv",
        description="Convert trimmed NeTEx SiteFrame to TSDUPD CSV files.",
    )
    parser.add_argument(
        "--input",
        required=True,
        help="Path to NeTEx SiteFrame XML file.",
    )
    parser.add_argument(
        "--csv-dir",
        default="./CSV",
        help="Output directory for CSV files (default: ./CSV).",
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
        csv_dir=Path(args.csv_dir),
        originator=args.originator,
    )


if __name__ == "__main__":
    main()
