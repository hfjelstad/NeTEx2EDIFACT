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
- Legacy scripts only (netex2csv.py, csv2SKDUPD.py): `pip install xmltodict toolz`

## Source files

Place source NeTEx ZIP files in `Source/`:

| File | Content |
|------|---------|
| `RailStations_latest.zip` | NSR Tiamat rail station export (`SiteFrame`) — used as NAP station reference |
| `<operator>_<date>.zip` | Operator timetable NeTEx ZIP with a shared file (`_*.xml`) and one or more journey files |

## TSDUPD — Station location messages

TSDUPD carries station identity, coordinates, names and synonyms. It is independent of timetables and only needs to be re-sent when station data changes.

### Direct (NeTEx → EDIFACT)

```bash
python netex2tsdupd.py \
  --input  "Source/RailStations_latest.zip" \
  --output NEW_TSDUPD/new_TSDUPD.r \
  --originator NSR
```

Output: `NEW_TSDUPD/new_TSDUPD.r`

### Via CSV intermediate (inspect/edit before generating EDIFACT)

```bash
# Step 1 — produce CSV files in CSV/
python netex2tsdupd_csv.py \
  --input      "Source/RailStations_latest.zip" \
  --csv-dir    ./CSV \
  --originator NSR

# Step 2 — build EDIFACT from CSV
python csv2TSDUPD.py --csv-dir ./CSV --output NEW_TSDUPD/new_TSDUPD.r
```

CSV files written to `CSV/`:

| File | Description |
|------|-------------|
| `meta.csv` | Message metadata (reference, dates, originator) |
| `TSDUPD_STOP.csv` | One row per station: UIC code, name, coordinates, country |
| `TSDUPD_SYNONYM.csv` | Alternative names by language (populated if source has `AlternativeName`) |
| `TSDUPD_MCT.csv` | Minimum connection times (empty — not modelled in NSR) |
| `TSDUPD_FOOTPATH.csv` | Inter-station footpaths (empty — not modelled in NSR) |

### UIC code resolution (station file)

The converter handles three encoding variants found in NSR exports:

| Pattern | Location | Notes |
|---------|----------|-------|
| v2.0 | `StopPlace/privateCodes/PrivateCode[@type='uicCode']` | Preferred |
| Legacy singleton | `StopPlace/PrivateCode` | 9-digit value, no type attribute |
| Raw Tiamat export | `StopPlace/keyList/KeyValue[Key='uicCode']` | 7-digit, zero-padded to 9 |

## SKDUPD — Train schedule messages

SKDUPD carries the full timetable: trains, stop-times, platforms, and operating days.

### Mode 1 — With NAP station file (recommended)

Resolves UIC codes and platform numbers via the station file:

```
ScheduledStopPoint
  → PassengerStopAssignment (timetable shared file)
      → NSR Quay (station file)
          → parent StopPlace/PrivateCode  →  Por.uic
          → Quay/PublicCode               →  Por.arrival_platform / departure_platform
```

#### Direct (NeTEx → EDIFACT)

```bash
python netex2skdupd.py \
  --timetable  "Source/flb_2024-12-05T14_37_53.106.zip" \
  --stations   "Source/RailStations_latest.zip" \
  --output     NEW_SKDUPD/new_SKDUPD.r \
  --originator FLB
```

#### Batch — all operators in one EDIFACT delivery

Processes all operator ZIPs in `Source/` (skipping the station ZIP) as a single
SKDUPD delivery. Uses `Configuration/` mapping files to populate
`Train.service_mode` (brand code) and `Train.service_provider` (operator code),
and builds ODI records from `ServiceFacilitySet` data where available.

```bash
python run_conversion.py \
  --source-dir Source/ \
  --output     NEW_SKDUPD/new_SKDUPD_batch.r \
  --originator NSR
```

Station ZIP is auto-detected from `--source-dir` (any file matching `RailStations*.zip`).
Override with `--stations` or `--station-pattern` if needed.

To approximate historical upload semantics (numeric provider code, transport-mode
service mode, and legacy ODI fallback behavior), add:

```bash
--legacy-upload-parity
```

#### Via CSV intermediate

```bash
# Step 1
python netex2skdupd_csv.py \
  --timetable  "Source/flb_2024-12-05T14_37_53.106.zip" \
  --stations   "Source/RailStations_latest.zip" \
  --csv-dir    ./CSV \
  --originator FLB

# Step 2
python csv2SKDUPD_merits.py --csv-dir ./CSV --output NEW_SKDUPD/new_SKDUPD.r
```

CSV files written to `CSV/`:

| File | Description |
|------|-------------|
| `meta.csv` | Message metadata |
| `SKDUPD_TRAIN.csv` | One row per `ServiceJourney`: train number, operator, first/last day, operation days bitmask |
| `SKDUPD_POR.csv` | One row per stop-time: UIC, arrival, departure, platform |
| `SKDUPD_RELATION.csv` | Connection guarantees (empty — not modelled in source) |
| `SKDUPD_ODI.csv` | On-demand information segments (empty — not modelled in source) |

### Operating days

Operating dates are resolved exclusively via `DatedServiceJourney → OperatingDayRef → OperatingDay/CalendarDate`. The `operation_days` column in `SKDUPD_TRAIN.csv` is a binary bitmask string from `first_day` to `last_day` inclusive.

DatedServiceJourney is required; conversion will produce empty operation_days if DSJ data is missing.

## Script inventory

| Script | Role |
|--------|------|
| `netex2tsdupd.py` | NeTEx station ZIP → TSDUPD EDIFACT (direct) |
| `netex2tsdupd_csv.py` | NeTEx station ZIP → TSDUPD CSV files |
| `csv2TSDUPD.py` | TSDUPD CSV files → TSDUPD EDIFACT (MERITS) |
| `netex2skdupd.py` | NeTEx timetable + station ZIPs → SKDUPD EDIFACT (direct, Mode 1) |
| `netex2skdupd_csv.py` | NeTEx timetable + station ZIPs → SKDUPD CSV files (Mode 1) |
| `csv2SKDUPD_merits.py` | SKDUPD CSV files → SKDUPD EDIFACT (MERITS) |
| `run_conversion.py` | **Batch** — all operator ZIPs in `Source/` → single SKDUPD EDIFACT |
| `csv2SKDUPD.py` | Legacy hand-rolled SKDUPD CSV → EDIFACT (kept for reference) |
| `netex2csv.py` | Legacy NeTEx → SKDUPD CSV (SKDUPD only, xmltodict-based) |

## Configuration

Mapping files in `Configuration/` are used by the legacy `netex2csv.py` pipeline:

Mapping files in `Configuration/` are used by `run_conversion.py` (and `netex2skdupd.py`):

| File | Description |
|------|-------------|
| `mapping_brand.txt` | NeTEx `TransportSubmode` → MERITS brand code (→ `Train.service_mode`). Format: `submode:code`, e.g. `regionalRail:92` |
| `mapping_facility.txt` | NeTEx facility name → MERITS ODI code (F=TFF/facility, S=ASD/service, R=PDT/reservation). E.g. `bistro:F47` |
| `mapping_service_mode.txt` | NeTEx `TransportMode` → MERITS mode code. E.g. `rail:37` |
