# NeTEx2EDIFACT

A study project to convert the **NeTEx Nordic profile** to **MERITS EDIFACT (SKDUPD)** format.

## Overview

The conversion is done in two steps:

1. **NeTEx → CSV** — parse NeTEx XML files and output intermediate CSV files
2. **CSV → SKDUPD** — convert the CSVs to MERITS EDIFACT SKDUPD messages using the [MERITS open-source tools](https://github.com/UnionInternationalCheminsdeFer/MERITS-open-source-tools/tree/main/Conversion%20SKDUPD)

## Requirements

- Python 3.x
- [xmltodict](https://pypi.org/project/xmltodict/) — `pip install xmltodict`
- [toolz](https://pypi.org/project/toolz/) — `pip install toolz`

## Usage

1. Place NeTEx XML files in the `NETEX/` directory
2. Run `netex2csv.py` to convert them to CSV files in the `CSV/` directory:
   ```
   python netex2csv.py
   ```
3. Run `csv2SKDUPD.py` to produce the SKDUPD EDIFACT output in `NEW_SKDUPD/`:
   ```
   python csv2SKDUPD.py
   ```

Alternatively, run `run.bat` to execute the full pipeline.

## Configuration

Mapping files in `Configuration/` control how NeTEx values are translated:

| File | Description |
|------|-------------|
| `mapping_brand.txt` | Brand/operator mappings |
| `mapping_facility.txt` | Facility type mappings |
| `mapping_service_mode.txt` | Service mode mappings |

## Rail Stations

A station location export (Tiamat) is included in `LOCATIONS/` and used to resolve stop place coordinates.
