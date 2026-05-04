# NeTEx2EDIFACT

Converts **NeTEx Nordic profile** data to **MERITS EDIFACT** format (both TSDUPD and SKDUPD).

## Documentation

- [TSDUPD Converter Guide](../Guides/TSDUPD/TSDUPD_Converter_Guide.md) - station/location conversion design, profile rationale, and pipeline choices.
- [SKDUPD Converter Guide](../Guides/SKDUPD/SKDUPD_Converter_Guide.md) - timetable conversion design, calendar logic, ODI handling, and converter trade-offs.

Source data is the Norwegian national access point (NSR/Entur):
- Station/stop place data — exported from Tiamat as a NeTEx `SiteFrame`
- Timetable data — operator NeTEx ZIPs containing `ServiceFrame` + `TimetableFrame`

Both message types are supported with two pipeline variants: a **direct** path (NeTEx → EDIFACT in one step) and a **CSV intermediate** path (NeTEx → CSV → EDIFACT) for inspection and manual correction.

## Requirements

- Python 3.10+
- MERITS open-source tools:
  ```
  pip install git+https://github.com/UnionInternationalCheminsdeFer/MERITS-open-source-tools.git
  ```

## Project layout

```
NeTEx2EDIFACT/
├── run.py                        ← single entry point (dispatcher)
├── converter/
│   ├── shared/                   ← NeTEx parsing + EDIFACT vocab (RICS, ISO, TZ)
│   ├── tsdupd/                   ← TSDUPD pipelines (direct, csv, csv→edifact)
│   └── skdupd/                   ← SKDUPD pipelines (direct, csv, csv→edifact, batch)
├── Configuration/                ← mapping files (brand, facility, service mode)
├── Source/                       ← input NeTEx ZIPs
├── CSV/                          ← intermediate CSV
├── NEW_TSDUPD/  NEW_SKDUPD/      ← output folders
└── scripts/debugging/            ← ad-hoc inspection scripts
```

All pipelines are invoked through `run.py`. Which pipeline runs is decided by
the combination of arguments supplied:

| Inputs                                           | Pipeline                 |
|--------------------------------------------------|--------------------------|
| `--input X.xml --output Y.r`                     | NeTEx → EDIFACT (direct) |
| `--input X.xml --csv-dir DIR`                    | NeTEx → CSV              |
| `--csv-dir DIR --output Y.r`                     | CSV → EDIFACT            |
| `--batch …` *(skdupd only)*                      | multi-operator batch     |

Show help: `python run.py --help`, `python run.py tsdupd --help`, `python run.py skdupd --help`.

## Source files

Place source NeTEx ZIP files in `Source/`:

| File | Content |
|------|---------|
| `RailStations_latest.zip` | NSR Tiamat rail station export (`SiteFrame`) — used as NAP station reference |
| `<operator>_<date>.zip`   | Operator timetable NeTEx ZIP with a shared file (`_*.xml`) and one or more journey files |

## TSDUPD — Station location messages

TSDUPD carries station identity, coordinates, names, synonyms and **minimum
connection times** (extracted from `SiteConnection` self-loops where
`From.ref == To.ref`). It is independent of timetables and only needs to be
re-sent when station data changes.

### Direct (NeTEx → EDIFACT)

```bash
python run.py tsdupd \
  --input  "Source/RailStations_latest.zip" \
  --output NEW_TSDUPD/new_TSDUPD.r \
  --originator NSR
```

Outputs:
- `NEW_TSDUPD/new_TSDUPD.r` — interchange file
- `NEW_TSDUPD/TSDUPD_<unix>.zip` — compressed delivery archive

### Via CSV intermediate

```bash
# Step 1 — produce CSV files in CSV/
python run.py tsdupd \
  --input      "Source/RailStations_latest.zip" \
  --csv-dir    ./CSV \
  --originator NSR

# Step 2 — build EDIFACT from CSV
python run.py tsdupd --csv-dir ./CSV --output NEW_TSDUPD/new_TSDUPD.r
```

CSV files written to `CSV/`:

| File | Description |
|------|-------------|
| `meta.csv` | Message metadata (reference, dates, originator) |
| `TSDUPD_STOP.csv` | One row per station: UIC code, name, coordinates, country |
| `TSDUPD_SYNONYM.csv` | Alternative names by language (populated if source has `AlternativeName`) |
| `TSDUPD_MCT.csv` | Minimum connection times (populated from `SiteConnection` self-loops) |
| `TSDUPD_FOOTPATH.csv` | Inter-station footpaths (empty — not modelled in NSR) |

### UIC code resolution (station file)

The converter handles three encoding variants found in NSR exports:

| Pattern           | Location                                              | Notes |
|-------------------|-------------------------------------------------------|-------|
| v2.0              | `StopPlace/privateCodes/PrivateCode[@type='uicCode']` | Preferred |
| Legacy singleton  | `StopPlace/PrivateCode`                               | 9-digit value, no type attribute |
| Raw Tiamat export | `StopPlace/keyList/KeyValue[Key='uicCode']`           | 7-digit, zero-padded to 9 |

## SKDUPD — Train schedule messages

SKDUPD carries the full timetable: trains, stop-times, platforms, and operating days.

UIC codes and platform numbers are resolved via the NAP station file:

```
ScheduledStopPoint
  → PassengerStopAssignment (timetable shared file)
      → NSR Quay (station file)
          → parent StopPlace/PrivateCode  →  Por.uic
          → Quay/PublicCode               →  Por.arrival_platform / departure_platform
```

### Direct (NeTEx → EDIFACT)

```bash
python run.py skdupd \
  --timetable  "Source/flb_2024-12-05T14_37_53.106.zip" \
  --stations   "Source/RailStations_latest.zip" \
  --output     NEW_SKDUPD/new_SKDUPD.r \
  --originator FLB
```

### Via CSV intermediate

```bash
# Step 1
python run.py skdupd \
  --timetable  "Source/flb_2024-12-05T14_37_53.106.zip" \
  --stations   "Source/RailStations_latest.zip" \
  --csv-dir    ./CSV \
  --originator FLB

# Step 2
python run.py skdupd --csv-dir ./CSV --output NEW_SKDUPD/new_SKDUPD.r
```

CSV files written to `CSV/`:

| File | Description |
|------|-------------|
| `meta.csv` | Message metadata |
| `SKDUPD_TRAIN.csv` | One row per `ServiceJourney`: train number, operator, first/last day, operation days bitmask |
| `SKDUPD_POR.csv` | One row per stop-time: UIC, arrival, departure, platform |
| `SKDUPD_RELATION.csv` | Connection guarantees (empty — not modelled in source) |
| `SKDUPD_ODI.csv` | On-demand information segments (populated from `ServiceFacilitySet` where available) |

### Batch — all operators in one EDIFACT delivery

Processes all operator ZIPs in `Source/` (skipping the station ZIP) as a single
SKDUPD delivery. Uses `Configuration/` mapping files to populate
`Train.service_mode` (brand code) and `Train.service_provider` (operator code),
and builds ODI records from `ServiceFacilitySet` data where available.

```bash
python run.py skdupd --batch \
  --source-dir Source/ \
  --output     NEW_SKDUPD/new_SKDUPD_batch.r \
  --originator NSR
```

Station ZIP is auto-detected from `--source-dir` (any file matching `RailStations*.zip`).
Override with `--stations` or `--station-pattern` if needed.

### Operating days

Operating dates are resolved exclusively via
`DatedServiceJourney → OperatingDayRef → OperatingDay/CalendarDate`. The
`operation_days` column in `SKDUPD_TRAIN.csv` is a binary bitmask string from
`first_day` to `last_day` inclusive.

DatedServiceJourney is required; conversion will produce empty
`operation_days` if DSJ data is missing.

## Module inventory

All modules live under the `converter/` package and can also be invoked
directly via `python -m converter.<sub>.<module>` if you need to bypass the
dispatcher.

| Module | Role |
|--------|------|
| `converter.shared.netex_helpers`     | Shared NeTEx XML parsing helpers (UIC, MCT, codespaces, …) |
| `converter.shared.edifact_mappings`  | RICS / ISO country / timezone tables, ASCII fold |
| `converter.tsdupd.netex2tsdupd`      | NeTEx station ZIP → TSDUPD EDIFACT (direct) |
| `converter.tsdupd.netex2tsdupd_csv`  | NeTEx station ZIP → TSDUPD CSV |
| `converter.tsdupd.csv2TSDUPD`        | TSDUPD CSV → TSDUPD EDIFACT (MERITS) |
| `converter.skdupd.netex2skdupd`      | NeTEx timetable + station ZIPs → SKDUPD EDIFACT (direct) |
| `converter.skdupd.netex2skdupd_csv`  | NeTEx timetable + station ZIPs → SKDUPD CSV |
| `converter.skdupd.csv2SKDUPD_merits` | SKDUPD CSV → SKDUPD EDIFACT (MERITS) |
| `converter.skdupd.run_conversion`    | Multi-operator batch over `Source/` |

## Configuration

Mapping files in `Configuration/` are used by the SKDUPD converters
(`netex2skdupd` and `run_conversion`):

| File | Description |
|------|-------------|
| `mapping_brand.txt`        | NeTEx `TransportSubmode` → MERITS brand code (→ `Train.service_mode`). Format: `submode:code`, e.g. `regionalRail:92` |
| `mapping_facility.txt`     | NeTEx facility name → MERITS ODI code (F=TFF/facility, S=ASD/service, R=PDT/reservation). E.g. `bistro:F47` |
| `mapping_service_mode.txt` | NeTEx `TransportMode` → MERITS mode code. E.g. `rail:37` |
