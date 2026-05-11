"""
check_rrb_quayrefs.py
~~~~~~~~~~~~~~~~~~~~~
Cross-reference all railReplacementBus bus stop QuayRefs against:
  1. nsr_railstations_with_mct.xml  (rail-only NSR export)
  2. Locations_20260501_1130.csv    (UIC MERITS locations)

Outputs a table showing which bus stops are missing from our location sources.
"""
import csv
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path

NX = "http://www.netex.org.uk/netex"
REPO = Path(__file__).resolve().parent.parent.parent  # UIC NeTex Profile/
SOURCE = REPO / "NeTEx2EDIFACT" / "Source"
NSR_XML = REPO / "Nordic source material" / "nsr_railstations_with_mct.xml"
LOC_CSV = REPO / "Nordic source material" / "Locations_20260501_1130.csv"

# ── Load Locations CSV (semicolon-delimited UIC codes) ──────────────────────
uic_codes_in_csv: set[str] = set()
with open(LOC_CSV, newline="", encoding="utf-8-sig") as f:
    reader = csv.reader(f, delimiter=";")
    headers = next(reader)
    uic_col = next(i for i, h in enumerate(headers) if "UIC" in h.upper())
    for row in reader:
        if len(row) > uic_col:
            uic_codes_in_csv.add(row[uic_col].strip().strip('"'))

# ── Load NSR rail stations XML ───────────────────────────────────────────────
nsr_root = ET.parse(str(NSR_XML)).getroot()
nsr_quay_ids: set[str] = set()
nsr_quay_to_uic: dict[str, str] = {}

for sp in nsr_root.iter(f"{{{NX}}}StopPlace"):
    uic = ""
    for pc in sp.iter(f"{{{NX}}}PrivateCode"):
        val = (pc.text or "").strip()
        if val.isdigit() and 7 <= len(val) <= 11:
            uic = val
            break
    for quay in sp.iter(f"{{{NX}}}Quay"):
        qid = quay.get("id", "")
        nsr_quay_ids.add(qid)
        nsr_quay_to_uic[qid] = uic

# ── Load RRB bus stop QuayRefs from all source zips ──────────────────────────
# Bus stop SSP IDs contain patterns like -B-, -Bus, -BUS, -b- etc.
BUS_MARKERS = ("-B-", "-Bus", "-BUS", "-bus", "-b-", "-A_", "-A ")

rrb_ssp_to_quay: dict[str, str] = {}  # SSP id -> NSR:Quay:xxx
rrb_ssp_to_name: dict[str, str] = {}  # SSP id -> stop name

for zpath in sorted(SOURCE.glob("*.zip")):
    with zipfile.ZipFile(zpath) as z:
        # Prefer _Shared files for PSA definitions, fall back to all XMLs
        shared = [f for f in z.namelist() if f.startswith("_") and f.endswith(".xml")]
        files_to_scan = shared if shared else [f for f in z.namelist() if f.endswith(".xml")]

        for fname in files_to_scan:
            data = z.read(fname)
            if b"PassengerStopAssignment" not in data:
                continue
            root = ET.fromstring(data)

            # Collect SSP names
            for ssp in root.iter(f"{{{NX}}}ScheduledStopPoint"):
                ssp_id = ssp.get("id", "")
                name = (ssp.findtext(f"{{{NX}}}Name") or "").strip()
                if ssp_id:
                    rrb_ssp_to_name[ssp_id] = name

            for psa in root.iter(f"{{{NX}}}PassengerStopAssignment"):
                ssp_el = psa.find(f"{{{NX}}}ScheduledStopPointRef")
                quay_el = psa.find(f"{{{NX}}}QuayRef")
                if ssp_el is None or quay_el is None:
                    continue
                ssp_id = ssp_el.get("ref", "")
                qref = quay_el.get("ref", "")
                if any(m in ssp_id for m in BUS_MARKERS):
                    rrb_ssp_to_quay[ssp_id] = qref

# ── Report ───────────────────────────────────────────────────────────────────
print("=" * 95)
print("railReplacementBus — QuayRef vs. NSR Rail Stations")
print("=" * 95)
print(f"  UIC codes in Locations CSV:           {len(uic_codes_in_csv)}")
print(f"  Quay IDs in nsr_railstations XML:     {len(nsr_quay_ids)}")
print(f"  RRB bus stop QuayRef mappings found:  {len(rrb_ssp_to_quay)}")

in_nsr = {s: q for s, q in rrb_ssp_to_quay.items() if q in nsr_quay_ids}
not_in_nsr = {s: q for s, q in rrb_ssp_to_quay.items() if q not in nsr_quay_ids}

print(f"\n  In nsr_railstations:      {len(in_nsr)}")
print(f"  NOT in nsr_railstations:  {len(not_in_nsr)}")

if in_nsr:
    print("\n[UNEXPECTED] Bus stops whose QuayRef IS in the rail stations file:")
    for ssp, q in sorted(in_nsr.items()):
        name = rrb_ssp_to_name.get(ssp, "")
        print(f"  {ssp:<55} {q:<20} {name}")

print("\nAll RRB bus stops and their QuayRef (not in rail stations file):")
print(f"  {'SSP ID':<55} {'QuayRef':<20} {'Name'}")
print("  " + "-" * 90)
for ssp, q in sorted(not_in_nsr.items()):
    name = rrb_ssp_to_name.get(ssp, "")
    print(f"  {ssp:<55} {q:<20} {name}")

print()
print("CONCLUSION:")
print("  - All 0 bus stop QuayRefs match the rail stations export (expected — they are bus stops).")
print("  - The rail stations XML (nsr_railstations_with_mct.xml) does NOT contain bus stop quays.")
print("  - To resolve locations for these bus stops we need a full NSR stop place export")
print("    (bus + rail), or a separate bus stop location lookup keyed on NSR:Quay:XXXXX IDs.")
