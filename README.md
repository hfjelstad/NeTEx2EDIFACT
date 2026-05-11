# NeTEx2EDIFACT

Converts **NeTEx** data to **MERITS EDIFACT** format (both TSDUPD and SKDUPD).

## Quick start

1. Place NeTEx files in `Source/`:
   - Any `.zip` or `.xml` files — the converter auto-detects content by scanning for `StopPlace` (→ TSDUPD) and `ServiceJourney` (→ SKDUPD) elements. No naming convention required.

2. Run:
   ```
   python convert.py
   ```
   Or double-click `convert.bat` on Windows.

3. Collect output from `Output/`:
   - `TSDUPD.r` + `TSDUPD_<unix>.zip` — station EDIFACT
   - `SKDUPD.r` + `SKDUPD_<unix>.zip` — timetable EDIFACT

The converter auto-detects file content, runs TTL-driven pre-flight validation,
converts both message types, archives source files with a conversion report,
and cleans up after itself.

## Documentation

- [TSDUPD Converter Guide](../Guides/TSDUPD/TSDUPD_Converter_Guide.md) — station/location conversion
- [SKDUPD Converter Guide](../Guides/SKDUPD/SKDUPD_Converter_Guide.md) — timetable conversion

## Requirements

- Python 3.10+
- MERITS open-source tools:
  ```
  pip install git+https://github.com/UnionInternationalCheminsdeFer/MERITS-open-source-tools.git
  ```

## Project layout

```
NeTEx2EDIFACT/
├── convert.py              ← zero-config entry point (drop files, run, done)
├── convert.bat             ← Windows double-click launcher
├── Converter/              ← all conversion code
│   ├── Shared/             ← NeTEx parsing + EDIFACT vocab (RICS, ISO, TZ)
│   ├── TSDUPD/             ← TSDUPD pipelines (direct, csv, csv→edifact)
│   ├── SKDUPD/             ← SKDUPD pipelines (direct, csv, csv→edifact, batch)
│   ├── validate.py         ← TTL-driven pre-flight validation
│   ├── run.py              ← power-user CLI with explicit args
│   └── tests/              ← test suite
├── Configuration/          ← mapping files (brand, facility, service mode, MCT)
├── Source/                 ← input: drop NeTEx ZIPs/XMLs here
├── Output/                 ← output: EDIFACT files appear here
├── Archive/                ← auto-archived source + report.txt per run
└── Legacy/                 ← deprecated scripts (gitignored)
```

## How it works

`convert.py` performs these steps automatically:

1. **Scan** — peeks inside each file in `Source/` to detect StopPlace (→ TSDUPD) or ServiceJourney (→ SKDUPD) content
2. **Validate** — checks rules from `uic-edifact-ontology.ttl` (existence of required elements, well-formedness)
3. **Convert TSDUPD** — stations with UIC codes → EDIFACT location messages
4. **Convert SKDUPD** — timetables × station index → EDIFACT train messages
5. **Archive** — moves source files to `Archive/<timestamp>/` with a `report.txt` log
6. **Clean** — clears `Output/` before each run

## Source files

| File | Content |
|------|---------|
| `RailStations_latest.zip` | Station export (SiteFrame) — rail + bus stops with UIC codes |
| `<operator>_<date>.zip` | Operator timetable NeTEx ZIP (ServiceFrame + TimetableFrame) |

The station file should contain `privateCodes/PrivateCode[@type='uicCode']` on each
StopPlace. Both rail stations (0076*) and bus stops (9976*) are supported.

## Power-user CLI

For fine-grained control, use `Converter/run.py` directly:

```bash
# TSDUPD — direct
python Converter/run.py tsdupd --input Source/stations.zip --output Output/TSDUPD.r

# SKDUPD — direct
python Converter/run.py skdupd --timetable Source/tt.zip --stations Source/stations.zip --output Output/SKDUPD.r

# SKDUPD — batch (all operators in Source/)
python Converter/run.py skdupd --batch --source-dir Source/ --output Output/SKDUPD.r
```

Show help: `python Converter/run.py --help`

## UIC code resolution

The converter handles three encoding variants found in NeTEx exports:

| Pattern | Location | Notes |
|---------|----------|-------|
| v2.0 (preferred) | `StopPlace/privateCodes/PrivateCode[@type='uicCode']` | Case-insensitive match |
| Legacy singleton | `StopPlace/PrivateCode` | Fallback: direct child, no type attribute |
| Tiamat export | `StopPlace/keyList/KeyValue[Key='uicCode']` | 7-digit, zero-padded to 9 |

## SKDUPD stop resolution

UIC codes and platforms are resolved via the station index:

```
ScheduledStopPoint
  → PassengerStopAssignment (timetable shared file)
      → Quay (station file)
          → parent StopPlace/PrivateCode  →  POR uic
          → Quay/PublicCode               →  POR platform
```

Journeys with <2 UIC-resolvable stops are skipped. Non-rail modes (bus, coach)
are included when their stops have UIC codes; mode breakdown is shown in output.

## Operating days

Resolved exclusively via `DatedServiceJourney → OperatingDayRef → OperatingDay/CalendarDate`.
The operation days bitmask runs from first_day to last_day inclusive.

## Configuration

Mapping files in `Configuration/`:

| File | Description |
|------|-------------|
| `mapping_brand.txt` | `TransportSubmode` → MERITS brand code (e.g. `regionalRail:92`) |
| `mapping_facility.txt` | Facility name → ODI code (e.g. `bistro:F47`) |
| `mapping_service_mode.txt` | `TransportMode` → mode code (e.g. `rail:37`, `bus:32`) |
| `merits_mct_lookup.csv` | Minimum connection times by UIC code |

## Testing

```bash
cd Converter
python -m pytest tests/ -q
```
