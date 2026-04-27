# -*- coding: utf-8 -*-
"""
netex2tsdupd_csv.py
~~~~~~~~~~~~~~~~~~~
Convert a trimmed NeTEx SiteFrame XML (NSR rail stations) to the CSV files
expected by the MERITS TSDUPD converter (csv2TSDUPD.py).

Output files written to ./CSV/:
  meta.csv
  TSDUPD_STOP.csv
  TSDUPD_SYNONYM.csv   (AlternativeName entries, if any)

Usage:
  python netex2tsdupd_csv.py [--input <xml>] [--csv-dir <dir>] [--originator <code>]

Defaults:
  --input       ../Nordic source material/tiamat-export-RailStations-202604262300285592.trimmed.uic9.xml
  --csv-dir     ./CSV
  --originator  NSR
"""

from __future__ import annotations

import argparse
import csv
import xml.etree.ElementTree as ET
from datetime import date
from pathlib import Path

NS = "http://www.netex.org.uk/netex"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _text(element, tag: str) -> str:
    """Return stripped text of first matching child tag, or ''."""
    el = element.find(f"{{{NS}}}{tag}")
    return el.text.strip() if el is not None and el.text else ""


def _attr(element, tag: str, attribute: str) -> str:
    """Return an attribute value of the first matching child tag, or ''."""
    el = element.find(f"{{{NS}}}{tag}")
    return el.get(attribute, "") if el is not None else ""


def _uic_code(stop_place) -> str:
    """
    Return UIC code for a StopPlace.
    Checks v2.0 privateCodes/PrivateCode[@type='uicCode'] first,
    then falls back to legacy singleton PrivateCode.
    """
    # v2.0 preferred
    for pc in stop_place.findall(f".//{{{NS}}}privateCodes/{{{NS}}}PrivateCode"):
        if pc.get("type", "").lower() == "uiccode":
            return pc.text.strip() if pc.text else ""
    # legacy singleton
    pc = stop_place.find(f"{{{NS}}}PrivateCode")
    if pc is not None and pc.text:
        return pc.text.strip()
    return ""


def _reservation_code(stop_place) -> str:
    """Return reservation code if present in privateCodes."""
    for pc in stop_place.findall(f".//{{{NS}}}privateCodes/{{{NS}}}PrivateCode"):
        if pc.get("type", "").lower() == "reservationcode":
            return pc.text.strip() if pc.text else ""
    return ""


def _country_from_uic(uic: str) -> str:
    """First 2 digits of a 9-digit UIC code are the country code."""
    return uic[:2] if len(uic) >= 2 else ""


def _coordinates(stop_place):
    """Return (latitude, longitude) strings or ('', '')."""
    lon_el = stop_place.find(f".//{{{NS}}}Centroid/{{{NS}}}Location/{{{NS}}}Longitude")
    lat_el = stop_place.find(f".//{{{NS}}}Centroid/{{{NS}}}Location/{{{NS}}}Latitude")
    lon = lon_el.text.strip() if lon_el is not None and lon_el.text else ""
    lat = lat_el.text.strip() if lat_el is not None and lat_el.text else ""
    return lat, lon


def _validity(stop_place):
    """Return (valid_from, valid_to) strings or ('', '')."""
    vb = stop_place.find(f"{{{NS}}}ValidBetween")
    if vb is None:
        return "", ""
    from_el = vb.find(f"{{{NS}}}FromDate")
    to_el = vb.find(f"{{{NS}}}ToDate")
    from_date = from_el.text[:10] if from_el is not None and from_el.text else ""
    to_date = to_el.text[:10] if to_el is not None and to_el.text else ""
    return from_date, to_date


def _alt_names(stop_place):
    """Yield (language, name) for each AlternativeName."""
    for an in stop_place.findall(f".//{{{NS}}}AlternativeName"):
        name_el = an.find(f"{{{NS}}}Name")
        lang = name_el.get("lang", "") if name_el is not None else ""
        name = name_el.text.strip() if name_el is not None and name_el.text else ""
        if name:
            yield lang, name


# ---------------------------------------------------------------------------
# Main conversion
# ---------------------------------------------------------------------------

def convert(xml_path: Path, csv_dir: Path, originator: str) -> None:
    csv_dir.mkdir(parents=True, exist_ok=True)

    tree = ET.parse(xml_path)
    root = tree.getroot()
    stop_places = root.findall(f".//{{{NS}}}StopPlace")
    print(f"Found {len(stop_places)} StopPlaces in {xml_path.name}")

    # ---- meta.csv ----
    today = date.today().isoformat()
    with open(csv_dir / "meta.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(["reference", "validity_first_date", "validity_last_date", "originator"])
        w.writerow([f"TSDUPD_{today}", today, "", originator])

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
        uic = _uic_code(sp)
        if not uic:
            # Skip stops without a UIC code – they are unusable in TSDUPD
            print(f"  SKIP {sp.get('id')} — no UIC code")
            continue

        name = _text(sp, "Name")
        lat, lon = _coordinates(sp)
        valid_from, valid_to = _validity(sp)
        country = _country_from_uic(uic)
        res_code = _reservation_code(sp)

        stop_rows.append([
            stop_id,
            "M",        # function_code: M = major station (default; adjust as needed)
            uic,
            name,
            "",         # location_short_name — not in NSR export
            lat,
            lon,
            valid_from,
            valid_to,
            "",         # default_transfer_time — not in NSR export
            country,
            "",         # timezone_1
            "",         # timezone_2
            res_code,
        ])

        for lang, alt_name in _alt_names(sp):
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
        default="../Nordic source material/tiamat-export-RailStations-202604262300285592.trimmed.uic9.xml",
        help="Path to trimmed NeTEx XML file.",
    )
    parser.add_argument(
        "--csv-dir",
        default="./CSV",
        help="Output directory for CSV files (default: ./CSV).",
    )
    parser.add_argument(
        "--originator",
        default="NSR",
        help="Originator code written to meta.csv (default: NSR).",
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
