# -*- coding: utf-8 -*-
"""
fetch_source.py — Populate Source/ for a conversion run
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Downloads the three Entur/Rutebanken aggregated NeTEx timetable ZIPs and
copies the modified NSR station file into Source/, so that a subsequent
``python convert.py`` finds everything it needs.

Usage:
  python fetch_source.py                # download + copy NSR (skip existing)
  python fetch_source.py --force        # re-download / re-copy everything
  python fetch_source.py --skip-download # only refresh the NSR station file
  python fetch_source.py --skip-nsr     # only download the timetable ZIPs

Files placed in Source/:
  rb_vyg-aggregated-netex.zip           (Vy)
  rb_sjn-aggregated-netex.zip           (SJ Norge)
  rb_goa-aggregated-netex.zip           (Go-Ahead Nordic)
  nsr_uic_stops_current_with_mct.xml    (station index, from Nordic source material/)
"""

from __future__ import annotations

import argparse
import shutil
import sys
import urllib.request
import zipfile
from pathlib import Path

# Timetable ZIPs published by Entur/Rutebanken (marduk production outbound).
TIMETABLE_URLS = [
    "https://storage.googleapis.com/marduk-production/outbound/netex/rb_vyg-aggregated-netex.zip",
    "https://storage.googleapis.com/marduk-production/outbound/netex/rb_sjn-aggregated-netex.zip",
    "https://storage.googleapis.com/marduk-production/outbound/netex/rb_goa-aggregated-netex.zip",
]

_HERE = Path(__file__).resolve().parent                     # NeTEx2EDIFACT/
SOURCE_DIR = _HERE / "Source"

# Modified NSR station file: use the workspace-root copy during local dev,
# and fall back to the version bundled in the repo (data/) when it is absent
# — e.g. on a CI runner that only checks out the converter repo.
_EXTERNAL_NSR = _HERE.parent / "Nordic source material" / "nsr_uic_stops_current_with_mct.xml"
_BUNDLED_NSR = _HERE / "data" / "nsr_uic_stops_current_with_mct.xml"
DEFAULT_NSR = _EXTERNAL_NSR if _EXTERNAL_NSR.exists() else _BUNDLED_NSR


def _human(size: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.1f} {unit}" if unit != "B" else f"{size} B"
        size /= 1024
    return f"{size:.1f} GB"


def download(url: str, dest_dir: Path, force: bool) -> None:
    """Stream a URL to dest_dir/<basename>, resuming via a .part temp file."""
    name = url.rsplit("/", 1)[-1]
    target = dest_dir / name
    if target.exists() and not force:
        print(f"  SKIP (exists): {name}  [{_human(target.stat().st_size)}]")
        return

    tmp = target.with_suffix(target.suffix + ".part")
    print(f"  Downloading {name} ...")
    req = urllib.request.Request(url, headers={"User-Agent": "netex2edifact-fetch/1.0"})
    with urllib.request.urlopen(req) as resp:  # noqa: S310 — fixed https googleapis URLs
        total = int(resp.headers.get("Content-Length", 0))
        read = 0
        with open(tmp, "wb") as fh:
            while True:
                chunk = resp.read(1 << 16)
                if not chunk:
                    break
                fh.write(chunk)
                read += len(chunk)
                if total:
                    pct = read * 100 // total
                    print(f"\r    {pct:3d}%  {_human(read)} / {_human(total)}", end="", flush=True)
        if total:
            print()

    if not zipfile.is_zipfile(tmp):
        tmp.unlink(missing_ok=True)
        raise SystemExit(f"Downloaded file is not a valid ZIP: {name}")
    tmp.replace(target)
    print(f"    OK: {name}  [{_human(target.stat().st_size)}]")


def copy_nsr(nsr_path: Path, dest_dir: Path, force: bool) -> None:
    """Copy the modified NSR station XML into Source/."""
    if not nsr_path.exists():
        raise SystemExit(f"NSR station file not found: {nsr_path}")
    target = dest_dir / nsr_path.name
    if target.exists() and not force:
        print(f"  SKIP (exists): {nsr_path.name}  [{_human(target.stat().st_size)}]")
        return
    shutil.copy2(nsr_path, target)
    print(f"  Copied station file: {nsr_path.name}  [{_human(target.stat().st_size)}]")


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="fetch_source",
        description="Download timetable ZIPs and copy the NSR station file into Source/.",
    )
    parser.add_argument("--force", action="store_true",
                        help="Re-download / re-copy files even if they already exist.")
    parser.add_argument("--skip-download", action="store_true",
                        help="Do not download timetable ZIPs.")
    parser.add_argument("--skip-nsr", action="store_true",
                        help="Do not copy the NSR station file.")
    parser.add_argument("--source-dir", default=str(SOURCE_DIR),
                        help="Destination directory (default: ./Source).")
    parser.add_argument("--nsr", default=str(DEFAULT_NSR),
                        help="Path to the modified NSR station XML.")
    return parser


def main() -> None:
    args = _build_arg_parser().parse_args()
    dest_dir = Path(args.source_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)
    print(f"Source directory: {dest_dir}")

    if not args.skip_download:
        print("\nTimetable ZIPs:")
        for url in TIMETABLE_URLS:
            download(url, dest_dir, args.force)

    if not args.skip_nsr:
        print("\nStation file:")
        copy_nsr(Path(args.nsr), dest_dir, args.force)

    print("\nDone. Run 'python convert.py' to produce EDIFACT in Output/.")


if __name__ == "__main__":
    main()
