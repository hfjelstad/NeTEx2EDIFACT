# -*- coding: utf-8 -*-
"""
Convert TSDUPD CSV files to TSDUPD EDIFACT using the MERITS open-source package.

Expected CSV inputs in a directory:
- meta.csv
- TSDUPD_STOP.csv
- TSDUPD_SYNONYM.csv (optional)
- TSDUPD_MCT.csv (optional)
- TSDUPD_FOOTPATH.csv (optional)

Default output:
- ./NEW_TSDUPD/new_TSDUPD.r
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Dict


REQUIRED_FILES = [
    "meta.csv",
    "TSDUPD_STOP.csv",
]

OPTIONAL_FILES = [
    "TSDUPD_SYNONYM.csv",
    "TSDUPD_MCT.csv",
    "TSDUPD_FOOTPATH.csv",
]


def _load_csv_content(csv_dir: Path, strict_optional: bool = False) -> Dict[str, str]:
    """Load required and optional CSV files into a dict keyed by file name."""
    payload: Dict[str, str] = {}

    missing_required = [name for name in REQUIRED_FILES if not (csv_dir / name).exists()]
    if missing_required:
        joined = ", ".join(missing_required)
        raise FileNotFoundError(f"Missing required TSDUPD CSV file(s) in {csv_dir}: {joined}")

    for name in REQUIRED_FILES + OPTIONAL_FILES:
        path = csv_dir / name
        if path.exists():
            payload[name] = path.read_text(encoding="utf-8-sig")
        elif name in OPTIONAL_FILES and strict_optional:
            raise FileNotFoundError(f"Missing optional file while --strict-optional is set: {path}")

    return payload


def convert(csv_dir: Path, output_file: Path, strict_optional: bool = False) -> None:
    """Run CSV -> TSDUPD conversion through the MERITS reference implementation."""
    try:
        from merits.tsdupd.csvs_to_edifact import CsvsToEdifact  # type: ignore
    except ImportError as exc:
        raise RuntimeError(
            "Could not import MERITS package. Install it first, for example: "
            "pip install git+https://github.com/UnionInternationalCheminsdeFer/MERITS-open-source-tools.git"
        ) from exc

    csv_payload = _load_csv_content(csv_dir=csv_dir, strict_optional=strict_optional)

    converter = CsvsToEdifact()
    converter.load_csvs(csv_file_name_2_content=csv_payload)
    edifact_text = converter.get()

    output_file.parent.mkdir(parents=True, exist_ok=True)
    output_file.write_text(edifact_text, encoding="utf-8")



def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="csv2TSDUPD",
        description="Convert TSDUPD CSV files to TSDUPD EDIFACT (.r).",
    )
    parser.add_argument(
        "--csv-dir",
        default="./CSV",
        help="Directory containing TSDUPD CSV inputs (default: ./CSV).",
    )
    parser.add_argument(
        "--output",
        default="./NEW_TSDUPD/new_TSDUPD.r",
        help="Output TSDUPD EDIFACT file path (default: ./NEW_TSDUPD/new_TSDUPD.r).",
    )
    parser.add_argument(
        "--strict-optional",
        action="store_true",
        help="If set, optional files must also exist.",
    )
    return parser


def main() -> None:
    parser = _build_arg_parser()
    args = parser.parse_args()

    csv_dir = Path(args.csv_dir)
    output_file = Path(args.output)

    convert(
        csv_dir=csv_dir,
        output_file=output_file,
        strict_optional=args.strict_optional,
    )

    print(f"Created TSDUPD EDIFACT file: {output_file}")


if __name__ == "__main__":
    main()
