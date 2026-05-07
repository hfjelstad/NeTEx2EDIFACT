# -*- coding: utf-8 -*-
"""
run.py -- single entry point for all NeTEx <-> EDIFACT pipelines.
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Usage examples
--------------
TSDUPD (stop / footpath / MCT data):

  # NeTEx XML -> TSDUPD EDIFACT (.r + zipped .zip)
  python run.py tsdupd --input file.xml --output NEW_TSDUPD/new_TSDUPD.r

  # NeTEx XML -> TSDUPD CSV intermediate
  python run.py tsdupd --input file.xml --csv-dir CSV/

  # TSDUPD CSV -> EDIFACT
  python run.py tsdupd --csv-dir CSV/ --output NEW_TSDUPD/new_TSDUPD.r

SKDUPD (timetable):

  # NeTEx timetable + station ZIP -> SKDUPD EDIFACT (single operator)
  python run.py skdupd --timetable file.zip --stations Source/RailStations_latest.zip \
                       --output NEW_SKDUPD/new_SKDUPD.r

  # NeTEx -> SKDUPD CSV intermediate
  python run.py skdupd --timetable file.zip --stations Source/RailStations_latest.zip \
                       --csv-dir CSV/

  # SKDUPD CSV -> EDIFACT
  python run.py skdupd --csv-dir CSV/ --output NEW_SKDUPD/new_SKDUPD.r

  # Multi-operator batch run
  python run.py skdupd --batch --source-dir Source/ --stations Source/RailStations_latest.zip \
                       --output NEW_SKDUPD/new_SKDUPD.r

The path that gets executed is decided by which arguments you supply:

  +----------------------------------------+---------------------------------+
  | Inputs                                 | Path executed                   |
  +----------------------------------------+---------------------------------+
  | --input + --output                     | NeTEx -> EDIFACT (direct)       |
  | --input + --csv-dir                    | NeTEx -> CSV (intermediate)     |
  | --csv-dir + --output (no --input)      | CSV   -> EDIFACT                |
  | --batch (skdupd only)                  | multi-operator batch run        |
  +----------------------------------------+---------------------------------+
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


# Make ``converter`` importable regardless of where the user runs ``python run.py``
sys.path.insert(0, str(Path(__file__).resolve().parent))


# ---------------------------------------------------------------------------
# TSDUPD dispatch
# ---------------------------------------------------------------------------

def _dispatch_tsdupd(args: argparse.Namespace) -> None:
    has_input = bool(args.input)
    has_output = bool(args.output)
    has_csv = bool(args.csv_dir)

    if has_input and has_output and not has_csv:
        # NeTEx XML → TSDUPD EDIFACT (direct)
        from Converter.TSDUPD.netex2tsdupd import convert
        convert(
            xml_path=Path(args.input),
            output_file=Path(args.output),
            originator=args.originator,
        )
    elif has_input and has_csv and not has_output:
        # NeTEx XML → TSDUPD CSV (intermediate)
        from Converter.TSDUPD.netex2tsdupd_csv import convert
        convert(
            xml_path=Path(args.input),
            csv_dir=Path(args.csv_dir),
            originator=args.originator,
        )
    elif has_csv and has_output and not has_input:
        # TSDUPD CSV -> EDIFACT
        from Converter.TSDUPD.csv2TSDUPD import convert
        convert(
            csv_dir=Path(args.csv_dir),
            output_file=Path(args.output),
        )
        print(f"Created TSDUPD EDIFACT file: {args.output}")
    else:
        raise SystemExit(
            "tsdupd: provide one of:\n"
            "  --input X.xml --output Y.r          (NeTEx → EDIFACT)\n"
            "  --input X.xml --csv-dir DIR         (NeTEx → CSV)\n"
            "  --csv-dir DIR --output Y.r          (CSV   → EDIFACT)"
        )


# ---------------------------------------------------------------------------
# SKDUPD dispatch
# ---------------------------------------------------------------------------

def _dispatch_skdupd(args: argparse.Namespace) -> None:
    if args.batch:
        # Multi-operator batch over a folder of timetable ZIPs — defer to the
        # batch script's own argument parser by re-shaping sys.argv.
        forwarded: list[str] = ["run_conversion.py"]
        if args.source_dir:
            forwarded += ["--source-dir", args.source_dir]
        if args.stations:
            forwarded += ["--stations", args.stations]
        if args.output:
            forwarded += ["--output", args.output]
        if args.originator:
            forwarded += ["--originator", args.originator]
        if args.config_dir:
            forwarded += ["--config-dir", args.config_dir]
        if args.station_pattern:
            forwarded += ["--station-pattern", args.station_pattern]
        sys.argv = forwarded
        from Converter.SKDUPD.run_conversion import main as batch_main
        batch_main()
        return

    has_tt = bool(args.timetable)
    has_stations = bool(args.stations)
    has_output = bool(args.output)
    has_csv = bool(args.csv_dir)

    if has_tt and has_stations and has_output and not has_csv:
        # NeTEx timetable + stations → SKDUPD EDIFACT (direct, single operator)
        from Converter.SKDUPD.netex2skdupd import main as direct_main
        forwarded = [
            "netex2skdupd.py",
            "--timetable", args.timetable,
            "--stations", args.stations,
            "--output", args.output,
        ]
        if args.originator:
            forwarded += ["--originator", args.originator]
        if args.config_dir:
            forwarded += ["--config-dir", args.config_dir]
        sys.argv = forwarded
        direct_main()
    elif has_tt and has_stations and has_csv and not has_output:
        # NeTEx timetable + stations → SKDUPD CSV
        from Converter.SKDUPD.netex2skdupd_csv import main as csv_main
        forwarded = [
            "netex2skdupd_csv.py",
            "--timetable", args.timetable,
            "--stations", args.stations,
            "--csv-dir", args.csv_dir,
        ]
        if args.originator:
            forwarded += ["--originator", args.originator]
        sys.argv = forwarded
        csv_main()
    elif has_csv and has_output and not has_tt:
        # SKDUPD CSV -> EDIFACT
        from Converter.SKDUPD.csv2SKDUPD_merits import convert
        convert(
            csv_dir=Path(args.csv_dir),
            output_file=Path(args.output),
        )
    else:
        raise SystemExit(
            "skdupd: provide one of:\n"
            "  --timetable X.zip --stations Y.zip --output Z.r   (NeTEx → EDIFACT)\n"
            "  --timetable X.zip --stations Y.zip --csv-dir DIR  (NeTEx → CSV)\n"
            "  --csv-dir DIR --output Z.r                         (CSV   → EDIFACT)\n"
            "  --batch --source-dir Source/ --stations Y.zip --output Z.r"
        )


# ---------------------------------------------------------------------------
# Argument parser
# ---------------------------------------------------------------------------

def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="run.py",
        description="Single entry point for NeTEx <-> EDIFACT (TSDUPD / SKDUPD) pipelines.",
        epilog="See module docstring for detailed examples.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="format", required=True, metavar="{tsdupd,skdupd}")

    # ---- tsdupd ----
    p_t = sub.add_parser("tsdupd", help="TSDUPD pipelines (stop data)")
    p_t.add_argument("--input", help="NeTEx SiteFrame XML input")
    p_t.add_argument("--csv-dir", help="CSV directory (input or output)")
    p_t.add_argument("--output", help="EDIFACT .r output file")
    p_t.add_argument("--originator", help="Override EDIFACT ORG/3036 RICS code")

    # ---- skdupd ----
    p_s = sub.add_parser("skdupd", help="SKDUPD pipelines (timetable)")
    p_s.add_argument("--timetable", help="NeTEx timetable ZIP (single operator)")
    p_s.add_argument("--stations", help="Station ZIP (RailStations_latest.zip)")
    p_s.add_argument("--csv-dir", help="CSV directory (input or output)")
    p_s.add_argument("--output", help="EDIFACT .r output file")
    p_s.add_argument("--originator", help="Override EDIFACT ORG/3036 RICS code")
    p_s.add_argument("--config-dir", help="Override Configuration/ directory")
    p_s.add_argument("--batch", action="store_true",
                     help="Multi-operator batch run over --source-dir")
    p_s.add_argument("--source-dir", help="Folder of timetable ZIPs (batch mode)")
    p_s.add_argument("--station-pattern", default="RailStations",
                     help="Station-ZIP filename pattern (batch mode)")

    return parser


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()
    if args.format == "tsdupd":
        _dispatch_tsdupd(args)
    elif args.format == "skdupd":
        _dispatch_skdupd(args)


if __name__ == "__main__":
    main()
