# -*- coding: utf-8 -*-
"""
convert.py — Zero-config converter
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Put NeTEx files in Source/, run this script, get EDIFACT in Output/.

  1. Place files in Source/:
     - One or more NeTEx files (.zip or .xml)
     - Can be separate station + timetable files, or one combined delivery

  2. Run:   python convert.py

  3. Collect output from Output/:
     - SKDUPD.r   — timetable EDIFACT (if timetable data found)
     - TSDUPD.r   — station EDIFACT (if station data found)

The script peeks inside each file to detect what it contains (SiteFrame,
TimetableFrame, or both). No naming conventions required.
"""

from __future__ import annotations

import io
import shutil
import sys
import zipfile
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path
from typing import NamedTuple

# Ensure imports work regardless of working directory
sys.path.insert(0, str(Path(__file__).resolve().parent))

SOURCE_DIR = Path(__file__).resolve().parent / "Source"
OUTPUT_DIR = Path(__file__).resolve().parent / "Output"
CONFIG_DIR = Path(__file__).resolve().parent / "Configuration"
ARCHIVE_DIR = Path(__file__).resolve().parent / "Archive"

NS = "http://www.netex.org.uk/netex"


class _TeeWriter(io.TextIOBase):
    """Write to both the original stdout and a StringIO buffer."""

    def __init__(self, original):
        self._original = original
        self.buffer = io.StringIO()

    def write(self, s):
        self._original.write(s)
        self.buffer.write(s)
        return len(s)

    def flush(self):
        self._original.flush()

    def get_report(self) -> str:
        return self.buffer.getvalue()


# ---------------------------------------------------------------------------
# Content detection
# ---------------------------------------------------------------------------

class FileContent(NamedTuple):
    path: Path
    has_stops: bool       # Contains StopPlace elements (→ TSDUPD)
    has_timetable: bool   # Contains ServiceJourney elements (→ SKDUPD)


def _peek_xml_root(root: ET.Element) -> tuple[bool, bool]:
    """Check whether an XML tree contains station and/or timetable data."""
    has_stops = root.find(f".//{{{NS}}}StopPlace") is not None
    has_timetable = root.find(f".//{{{NS}}}ServiceJourney") is not None
    return has_stops, has_timetable


def _peek_xml_stream(path: Path) -> tuple[bool, bool]:
    """Stream-scan an XML file to detect StopPlace / ServiceJourney.

    Stops as soon as both are found or after scanning 2 000 000 elements,
    whichever comes first — fast even for 400 MB+ files.
    """
    has_stops = False
    has_timetable = False
    count = 0
    try:
        for _, elem in ET.iterparse(str(path), events=("start",)):
            tag = elem.tag.split("}")[-1] if "}" in elem.tag else elem.tag
            if tag == "StopPlace":
                has_stops = True
            elif tag == "ServiceJourney":
                has_timetable = True
            elem.clear()
            if has_stops and has_timetable:
                break
            count += 1
            if count >= 2_000_000:
                break
    except ET.ParseError:
        pass
    return has_stops, has_timetable


def _peek_file(path: Path) -> FileContent:
    """Peek inside a NeTEx file (ZIP or XML) to detect content type."""
    has_stops = False
    has_timetable = False

    if path.suffix.lower() == ".zip":
        try:
            with zipfile.ZipFile(path) as z:
                xml_names = [n for n in z.namelist() if n.lower().endswith(".xml")]
                for name in xml_names:
                    root = ET.fromstring(z.read(name))
                    s, t = _peek_xml_root(root)
                    has_stops = has_stops or s
                    has_timetable = has_timetable or t
                    if has_stops and has_timetable:
                        break
        except (zipfile.BadZipFile, ET.ParseError):
            pass
    elif path.suffix.lower() == ".xml":
        has_stops, has_timetable = _peek_xml_stream(path)

    return FileContent(path=path, has_stops=has_stops, has_timetable=has_timetable)


def _discover_files() -> list[FileContent]:
    """Scan Source/ (and Source/TSDUPD/) for NeTEx files and classify them."""
    paths: list[Path] = []
    for ext in ("*.zip", "*.xml"):
        paths.extend(SOURCE_DIR.glob(ext))
    # Also check Source/TSDUPD/ subfolder
    tsdupd_dir = SOURCE_DIR / "TSDUPD"
    if tsdupd_dir.exists():
        for ext in ("*.zip", "*.xml"):
            paths.extend(tsdupd_dir.glob(ext))

    print(f"Scanning {len(paths)} file(s) in Source/ ...")
    results = []
    for p in sorted(paths):
        fc = _peek_file(p)
        label = []
        if fc.has_stops:
            label.append("stations")
        if fc.has_timetable:
            label.append("timetable")
        if not label:
            label.append("unknown")
        print(f"  {p.name:40s}  [{', '.join(label)}]")
        results.append(fc)
    return results


def _best_station_file(station_files: list[FileContent]) -> FileContent:
    """Pick the best station file: prefer dedicated (no timetable), then largest."""
    dedicated = [f for f in station_files if not f.has_timetable]
    candidates = dedicated if dedicated else station_files
    # Pick largest file (most likely to have the most stations)
    return max(candidates, key=lambda f: f.path.stat().st_size)


def _clean_output() -> None:
    """Remove previous output files (but keep .gitkeep)."""
    if not OUTPUT_DIR.exists():
        return
    for f in OUTPUT_DIR.iterdir():
        if f.name == ".gitkeep":
            continue
        if f.is_file():
            f.unlink()
        elif f.is_dir():
            shutil.rmtree(f)


def _archive_source(report: str = "") -> None:
    """Move Source/ contents into Archive/<timestamp>/ after successful conversion.
    
    Also saves the conversion report as report.txt in the archive folder.
    """
    files = [f for f in SOURCE_DIR.iterdir() if f.name != ".gitkeep" and not f.is_dir()]
    # Also check for subdirectories with content (e.g. Source/TSDUPD/)
    subdirs = [d for d in SOURCE_DIR.iterdir() if d.is_dir()]
    subdirs_with_files = [d for d in subdirs if any(d.iterdir())]

    if not files and not subdirs_with_files:
        return

    stamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    archive_path = ARCHIVE_DIR / stamp
    archive_path.mkdir(parents=True, exist_ok=True)

    for f in files:
        shutil.move(str(f), str(archive_path / f.name))
    for d in subdirs_with_files:
        shutil.move(str(d), str(archive_path / d.name))

    # Save conversion report
    if report:
        (archive_path / "report.txt").write_text(report, encoding="utf-8")

    print(f"\n  Archived source files -> Archive/{stamp}/")


def main() -> None:
    print("=" * 60)
    print("  NeTEx -> EDIFACT Converter")
    print("=" * 60)

    if not SOURCE_DIR.exists():
        SOURCE_DIR.mkdir(parents=True)
        print(f"\nCreated {SOURCE_DIR.relative_to(SOURCE_DIR.parent)}/")
        print("Place your NeTEx files there and run again.")
        return

    # Clean previous output
    _clean_output()

    # Discover and classify files by content
    files = _discover_files()

    if not files:
        print(f"\nNo NeTEx files (.zip/.xml) found in {SOURCE_DIR.relative_to(SOURCE_DIR.parent)}/")
        print("Place your NeTEx files there and run again.")
        return

    # Classify: which files have station data, which have timetables?
    station_files = [f for f in files if f.has_stops]
    timetable_files = [f for f in files if f.has_timetable]
    # Files with both (combined deliveries) contribute to both
    combined_files = [f for f in files if f.has_stops and f.has_timetable]

    if not station_files and not timetable_files:
        print("\nNo recognizable NeTEx content found (no StopPlace or ServiceJourney elements).")
        print("Check that your files contain valid NeTEx data.")
        return

    # ---- Pre-flight validation (TTL-driven) ----
    from Converter.validate import preflight_check, preflight_check_zip, print_results

    has_blocking_error = False
    print(f"\n{'-'*60}")
    print("Pre-flight validation (rules from uic-edifact-ontology.ttl)")

    for fc in files:
        target = "TSDUPD" if (fc.has_stops and not fc.has_timetable) else "SKDUPD"
        if fc.path.suffix == ".zip":
            errors, warnings = preflight_check_zip(fc.path, target)
        else:
            errors, warnings = preflight_check(fc.path, target)

        if errors or warnings:
            print(f"\n  {fc.path.name} ({target}):")
            print_results(fc.path, errors, warnings)
            if errors:
                has_blocking_error = True
        else:
            print(f"  OK: {fc.path.name}")

    if has_blocking_error:
        print(f"\n{'-'*60}")
        print("  FAILED: Validation failed -- fix the errors above before converting.")
        return

    print(f"{'-'*60}")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    print(f"\nOutput:  {OUTPUT_DIR.relative_to(OUTPUT_DIR.parent)}/")

    # ---- TSDUPD (stations) ----
    if station_files:
        sf = _best_station_file(station_files)
        print(f"\n{'-'*60}")
        print(f"TSDUPD -- stations from: {sf.path.name}")
        tsdupd_output = OUTPUT_DIR / "TSDUPD.r"
        try:
            from Converter.TSDUPD.netex2tsdupd import convert as tsdupd_convert
            tsdupd_convert(
                input_dir=sf.path.parent,
                output_file=tsdupd_output,
                originator=None,
                input_file=sf.path,
            )
            print(f"  OK: {tsdupd_output.name}")
        except Exception as e:
            print(f"  FAILED: TSDUPD: {e}")
    else:
        print("\nNo station data found -- skipping TSDUPD.")

    # ---- SKDUPD (timetables) ----
    if timetable_files:
        # Station file is needed for UIC code resolution — pick the best one
        station_for_skdupd = None
        if station_files:
            station_for_skdupd = _best_station_file(station_files).path

        # For combined files (one file with both), the station data is in the same file
        if not station_for_skdupd and combined_files:
            station_for_skdupd = combined_files[0].path

        if not station_for_skdupd:
            print(f"\nWARNING: Found timetable data but no station data for UIC code resolution.")
            print("  Add a file containing StopPlace elements to Source/.")
        else:
            # Timetable ZIPs (exclude the station-only file)
            tt_zips = [f.path for f in timetable_files if f.path.suffix.lower() == ".zip"]
            # If the station file is also a timetable ZIP, include it
            # If no ZIPs but we have combined XML files, handle that
            if not tt_zips:
                # Combined XML with both — use it as timetable source too
                tt_zips = [f.path for f in combined_files if f.path.suffix.lower() == ".zip"]

            if not tt_zips:
                print(f"\nWARNING: Timetable data found in XML but SKDUPD converter requires ZIP input.")
                print("  Package timetable XML into a ZIP file.")
            else:
                print(f"\n{'-'*60}")
                print(f"SKDUPD -- {len(tt_zips)} timetable file(s), stations from: {station_for_skdupd.name}")
                for z in tt_zips:
                    print(f"  - {z.name}")

                skdupd_output = OUTPUT_DIR / "SKDUPD.r"

                if len(tt_zips) == 1:
                    try:
                        from Converter.SKDUPD.netex2skdupd import convert as skdupd_convert
                        skdupd_convert(
                            timetable_zip=tt_zips[0],
                            station_zip=station_for_skdupd,
                            output_file=skdupd_output,
                            originator=None,
                            config_dir=CONFIG_DIR if CONFIG_DIR.exists() else None,
                        )
                        print(f"  OK: {skdupd_output.name}")
                    except Exception as e:
                        print(f"  FAILED: SKDUPD failed: {e}")
                else:
                    try:
                        from Converter.SKDUPD.run_conversion import convert_batch
                        from Converter.Shared.netex_helpers import participant_ref

                        # Derive participant name from first timetable
                        derived_participant = None
                        with zipfile.ZipFile(tt_zips[0]) as z:
                            xml_names = [n for n in z.namelist() if n.endswith(".xml")]
                            if xml_names:
                                root = ET.fromstring(z.read(xml_names[0]))
                                derived_participant = participant_ref(root)

                        if not derived_participant:
                            raise RuntimeError(
                                "Cannot derive originator -- no ParticipantRef in timetable files. "
                                "Use run.py with --originator <RICS-code> instead."
                            )

                        convert_batch(
                            source_dir=SOURCE_DIR,
                            station_zip=station_for_skdupd,
                            output_file=skdupd_output,
                            originator=derived_participant,
                            config_dir=CONFIG_DIR if CONFIG_DIR.exists() else Path("."),
                        )
                        print(f"  OK: {skdupd_output.name}")
                    except Exception as e:
                        print(f"  FAILED: SKDUPD batch: {e}")
    else:
        print("\nNo timetable data found -- skipping SKDUPD.")

    # Archive source files after conversion
    _archive_source(report=_tee.get_report() if _tee else "")

    print(f"\n{'='*60}")
    print("  Done. Output in Output/")
    print("=" * 60)


_tee: _TeeWriter | None = None

if __name__ == "__main__":
    import time as _t
    _tee = _TeeWriter(sys.stdout)
    sys.stdout = _tee
    _start = _t.perf_counter()
    main()
    elapsed = _t.perf_counter() - _start
    print(f"\n  Total time: {elapsed:.1f}s")
    sys.stdout = _tee._original
