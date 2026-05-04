# -*- coding: utf-8 -*-
"""
netex2skdupd_csv.py  —  NeTEx timetable + NAP station file → SKDUPD CSV files
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Produces inspectable/editable CSV intermediates that can then be fed to
csv2SKDUPD.py to generate the final EDIFACT.

Output files written to --csv-dir (default ./CSV/):
  meta.csv
  SKDUPD_TRAIN.csv
  SKDUPD_POR.csv
  SKDUPD_RELATION.csv   (empty — no relation data in source)
  SKDUPD_ODI.csv        (empty — no ODI data in source)

Usage:
  python netex2skdupd_csv.py --timetable Source/flb_2024-12-05T14_37_53.106.zip
                              --stations  Source/RailStations_latest.zip
                              [--csv-dir  ./CSV]
                              [--originator FLB]
"""

from __future__ import annotations

import argparse
import csv
from pathlib import Path

# Re-use all parsing/lookup and build logic from the direct converter
from converter.skdupd.netex2skdupd import (
    TimetableData,
    _build_station_index,
    build_trains_and_pors,
)

from merits.skdupd import definition
from merits.skdupd.csv_model import Meta, Odi, Por, Relation, Train

from datetime import date
import dataclasses


# ---------------------------------------------------------------------------
# CSV writer
# ---------------------------------------------------------------------------

def _write_csv(path: Path, cls, rows: list) -> None:
    headers = [f.name for f in dataclasses.fields(cls)]
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(headers)
        for row in rows:
            w.writerow([
                "" if v is None else str(v)
                for v in dataclasses.astuple(row)
            ])


# ---------------------------------------------------------------------------
# Main conversion
# ---------------------------------------------------------------------------

def convert(
    timetable_zip: Path,
    station_zip: Path,
    csv_dir: Path,
    originator: str,
) -> None:
    csv_dir.mkdir(parents=True, exist_ok=True)

    print(f"Loading station index from {station_zip.name} ...")
    quay_index = _build_station_index(station_zip)
    print(f"  {len(quay_index)} quays indexed")

    print(f"Parsing timetable from {timetable_zip.name} ...")
    tt = TimetableData(timetable_zip)
    print(f"  {len(tt.ssp_to_quay)} SSP→Quay assignments")
    print(f"  {len(tt.spijp_to_ssp)} StopPointInJourneyPattern entries")

    meta_list, trains, pors = build_trains_and_pors(tt, quay_index, originator)

    _write_csv(csv_dir / "meta.csv", Meta, meta_list)
    _write_csv(csv_dir / "SKDUPD_TRAIN.csv", Train, trains)
    _write_csv(csv_dir / "SKDUPD_POR.csv", Por, pors)
    _write_csv(csv_dir / "SKDUPD_RELATION.csv", Relation, [])
    _write_csv(csv_dir / "SKDUPD_ODI.csv", Odi, [])

    print(f"Written CSVs to {csv_dir}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="netex2skdupd_csv",
        description="Convert NeTEx timetable + NAP station file to SKDUPD CSV intermediates.",
    )
    parser.add_argument("--timetable", required=True)
    parser.add_argument("--stations", required=True)
    parser.add_argument("--csv-dir", default="./CSV")
    parser.add_argument("--originator", default="NSR")
    return parser


def main() -> None:
    args = _build_arg_parser().parse_args()
    convert(
        timetable_zip=Path(args.timetable),
        station_zip=Path(args.stations),
        csv_dir=Path(args.csv_dir),
        originator=args.originator,
    )


if __name__ == "__main__":
    main()
