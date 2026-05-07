# -*- coding: utf-8 -*-
"""
csv2SKDUPD_merits.py
~~~~~~~~~~~~~~~~~~~~
Convert SKDUPD CSV files to SKDUPD EDIFACT using the MERITS open-source package.

Expected CSV inputs in --csv-dir (default ./CSV/):
  meta.csv              (required)
  SKDUPD_TRAIN.csv      (required)
  SKDUPD_POR.csv        (required)
  SKDUPD_RELATION.csv   (optional)
  SKDUPD_ODI.csv        (optional)

Default output:
  ./NEW_SKDUPD/new_SKDUPD.r

Note: The legacy csv2SKDUPD.py (hand-rolled, no MERITS dependency) is kept for
reference. This file is the MERITS-based equivalent.
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Dict

from merits.skdupd import definition

REQUIRED_FILES = [
    "meta.csv",
    definition.TRAIN_FILE_NAME,
    definition.POR_FILE_NAME,
]

OPTIONAL_FILES = [
    definition.RELATION_FILE_NAME,
    definition.ODI_FILE_NAME,
]


def _load_csv_content(csv_dir: Path) -> Dict[str, str]:
    missing = [name for name in REQUIRED_FILES if not (csv_dir / name).exists()]
    if missing:
        raise FileNotFoundError(
            f"Missing required SKDUPD CSV file(s) in {csv_dir}: {', '.join(missing)}"
        )
    payload: Dict[str, str] = {}
    for name in REQUIRED_FILES + OPTIONAL_FILES:
        path = csv_dir / name
        if path.exists():
            payload[name] = path.read_text(encoding="utf-8-sig")
    return payload


def convert(csv_dir: Path, output_file: Path) -> None:
    from merits.skdupd.csvs_to_edifact import CsvsToEdifact

    payload = _load_csv_content(csv_dir)
    converter = CsvsToEdifact()
    converter.load_csvs(csv_file_name_2_content=payload)
    edifact_text = converter.get()

    output_file.parent.mkdir(parents=True, exist_ok=True)
    output_file.write_text(edifact_text, encoding="utf-8")
    print(f"Created SKDUPD EDIFACT file: {output_file}")


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="csv2SKDUPD_merits",
        description="Convert SKDUPD CSV files to SKDUPD EDIFACT (.r) via MERITS.",
    )
    parser.add_argument("--csv-dir", default="./CSV")
    parser.add_argument("--output", default="./NEW_SKDUPD/new_SKDUPD.r")
    return parser


def main() -> None:
    args = _build_arg_parser().parse_args()
    convert(csv_dir=Path(args.csv_dir), output_file=Path(args.output))


if __name__ == "__main__":
    main()
