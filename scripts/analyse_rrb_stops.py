"""
analyse_rrb_stops.py
~~~~~~~~~~~~~~~~~~~~~
Step 1: Find all railReplacementBus stops used across source zips.
Step 2: Check which of those stops exist in the location source data.
Step 3: Report which stops are missing and need to be added.
"""
from __future__ import annotations
import csv
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path

NX = "http://www.netex.org.uk/netex"

REPO_ROOT = Path(__file__).resolve().parent.parent.parent  # UIC NeTex Profile/
SOURCE_DIR = Path(__file__).resolve().parent.parent / "Source"
LOCATIONS_CSV = REPO_ROOT / "Nordic source material" / "Locations_20260501_1130.csv"
NSR_XML = REPO_ROOT / "Nordic source material" / "nsr_railstations_with_mct.xml"

SOURCE_ZIPS = sorted(SOURCE_DIR.glob("*.zip"))

# ---------------------------------------------------------------------------
# Step 1: Collect all ScheduledStopPoints defined in source zips
#         AND all SSP refs used in railReplacementBus journeys
# ---------------------------------------------------------------------------
all_ssp_defined: dict[str, dict] = {}   # id -> {name, uic_code}
rrb_ssp_refs: set[str] = set()
rrb_files: list[str] = []

for zpath in SOURCE_ZIPS:
    with zipfile.ZipFile(zpath) as z:
        for fname in z.namelist():
            if not fname.endswith(".xml"):
                continue
            data = z.read(fname)
            try:
                root = ET.fromstring(data)
            except ET.ParseError:
                continue

            # Collect SSP definitions
            for ssp in root.iter(f"{{{NX}}}ScheduledStopPoint"):
                ssp_id = ssp.get("id", "")
                if not ssp_id:
                    continue
                name = (ssp.findtext(f"{{{NX}}}Name") or "").strip()
                # Look for UIC/Private code
                uic = ""
                for kv in ssp.iter(f"{{{NX}}}PrivateCode"):
                    uic = (kv.text or "").strip()
                    break
                all_ssp_defined[ssp_id] = {"name": name, "uic": uic}

            if b"railReplacementBus" not in data:
                continue

            rrb_files.append(f"{zpath.name}/{fname}")

            # Find all RRB journey pattern IDs
            rrb_jp_ids: set[str] = set()
            for sj in root.iter(f"{{{NX}}}ServiceJourney"):
                bsub = sj.find(f".//{{{NX}}}BusSubmode")
                if bsub is None or bsub.text != "railReplacementBus":
                    continue
                # JourneyPatternRef
                for child in sj:
                    tag = child.tag.split("}")[-1]
                    if "JourneyPatternRef" in tag or "PatternRef" in tag:
                        rrb_jp_ids.add(child.get("ref", ""))
                # FromStopPointRef / ToStopPointRef inside JourneyPart
                for jp_part in sj.iter(f"{{{NX}}}JourneyPart"):
                    for rtag in ("FromStopPointRef", "ToStopPointRef"):
                        ref_el = jp_part.find(f"{{{NX}}}{rtag}")
                        if ref_el is not None:
                            rrb_ssp_refs.add(ref_el.get("ref", ""))

            # Collect stop refs from those journey patterns
            for jp in root.iter(f"{{{NX}}}JourneyPattern"):
                if jp.get("id") not in rrb_jp_ids:
                    continue
                for spijp in jp.iter(f"{{{NX}}}StopPointInJourneyPattern"):
                    ref_el = spijp.find(f"{{{NX}}}ScheduledStopPointRef")
                    if ref_el is not None:
                        rrb_ssp_refs.add(ref_el.get("ref", ""))
                for ref_el in jp.iter(f"{{{NX}}}ScheduledStopPointRef"):
                    rrb_ssp_refs.add(ref_el.get("ref", ""))

rrb_ssp_refs.discard("")

# ---------------------------------------------------------------------------
# Step 2: Check against Locations CSV
# ---------------------------------------------------------------------------
locations_by_id: dict[str, dict] = {}
if LOCATIONS_CSV.exists():
    with open(LOCATIONS_CSV, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            # Try common column names for NSR/stop ID
            for col in ("id", "Id", "StopPlaceId", "stopPlaceId", "NSR_ID"):
                if col in row and row[col]:
                    locations_by_id[row[col]] = row
                    break

# Also check NSR XML for UIC codes
nsr_uic_codes: set[str] = set()
if NSR_XML.exists():
    nsr_root = ET.parse(str(NSR_XML)).getroot()
    NX_NS = "http://www.netex.org.uk/netex"
    for pc in nsr_root.iter(f"{{{NX_NS}}}PrivateCode"):
        val = (pc.text or "").strip()
        if val and val.isdigit() and len(val) in (5, 7):
            nsr_uic_codes.add(val)

# ---------------------------------------------------------------------------
# Step 3: Report
# ---------------------------------------------------------------------------
defined_in_source = {s for s in rrb_ssp_refs if s in all_ssp_defined}
missing_from_source = {s for s in rrb_ssp_refs if s not in all_ssp_defined}

print("=" * 65)
print("RailReplacementBus Stop Analysis")
print("=" * 65)
print(f"\nSource zips scanned: {len(SOURCE_ZIPS)}")
print(f"Files with railReplacementBus: {len(rrb_files)}")
for f in rrb_files:
    print(f"  {f}")
print(f"\nTotal SSPs defined in source: {len(all_ssp_defined)}")
print(f"Unique SSP refs used in RRB journeys: {len(rrb_ssp_refs)}")
print(f"  -> Defined in source:  {len(defined_in_source)}")
print(f"  -> Missing from source: {len(missing_from_source)}")

if defined_in_source:
    print("\nDefined RRB stops (with names from source):")
    for s in sorted(defined_in_source):
        info = all_ssp_defined[s]
        print(f"  {s:<50}  {info['name']:<30}  UIC:{info['uic']}")

if missing_from_source:
    print("\n⚠  Stops referenced in RRB journeys but NOT defined in any source file:")
    for s in sorted(missing_from_source):
        print(f"  {s}")

print(f"\nLocations CSV rows loaded: {len(locations_by_id)}")
print(f"NSR UIC codes in XML:      {len(nsr_uic_codes)}")
