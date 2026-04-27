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
  --originator NSR
"""

from __future__ import annotations

import argparse
import xml.etree.ElementTree as ET
from dataclasses import asdict, fields
from datetime import date
from pathlib import Path
from typing import Iterable, List, Type, TypeVar

from merits.csvs_zip.rows import RowsInMemory
from merits.tsdupd.csv_model import Footpath, Mct, Meta, Stop, Synonym
from merits.tsdupd.csvs_to_edifact import CsvsToEdifact
from merits.tsdupd import definition

NS = "http://www.netex.org.uk/netex"
T = TypeVar("T")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _text(element, tag: str) -> str:
    el = element.find(f"{{{NS}}}{tag}")
    return el.text.strip() if el is not None and el.text else ""


def _uic_code(stop_place) -> str:
    # Requires: privateCodes/PrivateCode[@type='uicCode'] with full 9-digit value.
    for pc in stop_place.findall(f".//{{{NS}}}privateCodes/{{{NS}}}PrivateCode"):
        if pc.get("type", "").lower() == "uiccode":
            return pc.text.strip() if pc.text else ""
    return ""


def _reservation_code(stop_place) -> str:
    for pc in stop_place.findall(f".//{{{NS}}}privateCodes/{{{NS}}}PrivateCode"):
        if pc.get("type", "").lower() == "reservationcode":
            return pc.text.strip() if pc.text else ""
    return ""


def _country_from_uic(uic: str) -> str:
    return uic[:2] if len(uic) >= 2 else ""


def _coordinates(stop_place):
    lon_el = stop_place.find(f".//{{{NS}}}Centroid/{{{NS}}}Location/{{{NS}}}Longitude")
    lat_el = stop_place.find(f".//{{{NS}}}Centroid/{{{NS}}}Location/{{{NS}}}Latitude")
    lon = lon_el.text.strip() if lon_el is not None and lon_el.text else ""
    lat = lat_el.text.strip() if lat_el is not None and lat_el.text else ""
    return lat, lon


def _validity(stop_place):
    vb = stop_place.find(f"{{{NS}}}ValidBetween")
    if vb is None:
        return "", ""
    from_el = vb.find(f"{{{NS}}}FromDate")
    to_el = vb.find(f"{{{NS}}}ToDate")
    return (
        from_el.text[:10] if from_el is not None and from_el.text else "",
        to_el.text[:10] if to_el is not None and to_el.text else "",
    )


def _alt_names(stop_place):
    for an in stop_place.findall(f".//{{{NS}}}AlternativeName"):
        name_el = an.find(f"{{{NS}}}Name")
        lang = name_el.get("lang", "") if name_el is not None else ""
        name = name_el.text.strip() if name_el is not None and name_el.text else ""
        if name:
            yield lang, name


def _rows(instances: List[T], cls: Type[T]) -> RowsInMemory:
    """Wrap a list of dataclass instances as RowsInMemory for MERITS."""
    headers = [f.name for f in fields(cls)]
    data = [
        {k: ("" if v is None else str(v)) for k, v in asdict(obj).items()}
        for obj in instances
    ]
    return RowsInMemory(data=data, headers=headers)


# ---------------------------------------------------------------------------
# Conversion
# ---------------------------------------------------------------------------

def convert(xml_path: Path, output_file: Path, originator: str) -> None:
    tree = ET.parse(xml_path)
    root = tree.getroot()
    stop_places = root.findall(f".//{{{NS}}}StopPlace")
    print(f"Found {len(stop_places)} StopPlaces in {xml_path.name}")

    today = date.today().isoformat()
    meta_list = [Meta(
        reference=f"TSDUPD_{today}",
        validity_first_date=today,
        validity_last_date=None,
        originator=originator,
    )]

    stops: List[Stop] = []
    synonyms: List[Synonym] = []
    stop_id = 0
    synonym_id = 0

    for sp in stop_places:
        uic = _uic_code(sp)
        if not uic:
            continue

        stop_id += 1
        name = _text(sp, "Name")
        lat, lon = _coordinates(sp)
        valid_from, valid_to = _validity(sp)

        stops.append(Stop(
            stop_id=stop_id,
            function_code="M",
            uic_code=uic,
            location_name=name,
            location_short_name=None,
            latitude=lat or None,
            longitude=lon or None,
            valid_from=valid_from or None,
            valid_to=valid_to or None,
            default_transfer_time=None,
            country=_country_from_uic(uic),
            timezone_1=None,
            timezone_2=None,
            reservation_code=_reservation_code(sp) or None,
        ))

        for lang, alt_name in _alt_names(sp):
            synonym_id += 1
            synonyms.append(Synonym(
                synonym_id=synonym_id,
                stop_id=stop_id,
                uic_code=uic,
                language=lang,
                synonym=alt_name,
            ))

    print(f"Converted {len(stops)} stops, {len(synonyms)} synonyms")

    converter = CsvsToEdifact()
    converter.load({
        definition.META_FILE_NAME:     _rows(meta_list, Meta),
        definition.STOP_FILE_NAME:     _rows(stops, Stop),
        definition.SYNONYM_FILE_NAME:  _rows(synonyms, Synonym),
        definition.MCT_FILE_NAME:      _rows([], Mct),
        definition.FOOTPATH_FILE_NAME: _rows([], Footpath),
    })
    edifact_text = converter.get()

    output_file.parent.mkdir(parents=True, exist_ok=True)
    output_file.write_text(edifact_text, encoding="utf-8")
    print(f"Written TSDUPD EDIFACT to {output_file}")


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
        default="NSR",
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
