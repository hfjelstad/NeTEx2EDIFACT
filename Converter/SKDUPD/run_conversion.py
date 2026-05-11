# -*- coding: utf-8 -*-
"""
run_conversion.py  —  Batch multi-operator NeTEx → SKDUPD EDIFACT converter
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Processes all timetable ZIPs in a source folder (skipping station ZIPs) as a
single SKDUPD delivery.  Configuration/ mapping files are used to populate:

  * Train.service_mode      ← Configuration/mapping_brand.txt
                              (NeTEx TransportSubmode → MERITS brand code)
  * Train.service_provider  ← OperatorRef last segment (e.g. 'NSB')
  * Train.service_mode tariff ← Configuration/mapping_service_mode.txt
                              (NeTEx TransportMode → MERITS mode code, informational)

ODI (facility) records are derived from mapping_facility.txt when
ServiceFacilitySet data is present on JourneyParts.

Usage:
  python run_conversion.py
      --source-dir  Source/
      --stations    Source/stations.zip
      --output      NEW_SKDUPD/new_SKDUPD.r
      [--originator <RICS-code>]
      [--config-dir Configuration/]
      [--station-pattern RailStations]
"""

from __future__ import annotations

import sys
from pathlib import Path
# Ensure the project root is on sys.path when this script is run directly
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import argparse
import re
import time
import zipfile
import xml.etree.ElementTree as ET
from dataclasses import asdict, fields
from datetime import date
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Type, TypeVar

from merits.csvs_zip.rows import RowsInMemory
from merits.skdupd.csv_model import Meta, Odi, Por, Relation, Train
from merits.skdupd.csvs_to_edifact import CsvsToEdifact
from merits.skdupd import definition

from Converter.SKDUPD.netex2skdupd import (
    TimetableData,
    _build_station_index,
    build_trains_and_pors,
    _rows,
    load_mapping,
    DEFAULT_CONFIG_DIR,
)
from Converter.Shared.edifact_mappings import resolve_originator

NS = "http://www.netex.org.uk/netex"


def _local_name(tag: str) -> str:
    return tag.split("}")[-1] if "}" in tag else tag


def _child_text(parent: ET.Element, child_local_name: str) -> str:
    for child in parent:
        if _local_name(child.tag) == child_local_name:
            return (child.text or "").strip()
    return ""


def _service_submode_value(sj: ET.Element) -> str:
    submode_el = sj.find(f".//{{{NS}}}TransportSubmode")
    if submode_el is None:
        return ""
    for child in submode_el:
        txt = (child.text or "").strip()
        if txt:
            return txt
    return ""


def _journeypart_stop_range(
        jp: ET.Element,
        spijp_order: Dict[str, int],
        por_stop_numbers: List[int],
) -> Tuple[str, str]:
        """
        Resolve JourneyPart coverage range as SKDUPD stop numbers.

        Preferred path:
            FromPointInJourneyPatternRef / ToPointInJourneyPatternRef -> SPiJP order

        Fallbacks:
            first/last available POR stop number for the train.
        """
        if not por_stop_numbers:
                return "1", "1"

        default_from = min(por_stop_numbers)
        default_to = max(por_stop_numbers)

        from_ref_el = jp.find(f"{{{NS}}}FromPointInJourneyPatternRef")
        to_ref_el = jp.find(f"{{{NS}}}ToPointInJourneyPatternRef")

        from_ref = from_ref_el.get("ref", "") if from_ref_el is not None else ""
        to_ref = to_ref_el.get("ref", "") if to_ref_el is not None else ""

        from_stop = spijp_order.get(from_ref, default_from)
        to_stop = spijp_order.get(to_ref, default_to)

        if from_stop > to_stop:
                from_stop, to_stop = to_stop, from_stop

        return str(from_stop), str(to_stop)


def _operator_rics_map(tt: TimetableData) -> Dict[str, str]:
    """Build OperatorRef -> RICS mapping from shared operators (legacy behavior)."""
    result: Dict[str, str] = {}
    root = tt.shared_root
    if root is None:
        return result

    for op in root.findall(f".//{{{NS}}}Operator"):
        op_id = op.get("id", "")
        rics = ""
        for kv in op.iter():
            if _local_name(kv.tag) != "KeyValue":
                continue
            key = _child_text(kv, "Key")
            val = _child_text(kv, "Value")
            if key == "RICS code" and val:
                rics = val
                break
        if op_id and rics:
            result[op_id] = rics
            result[op_id.split(":")[-1]] = rics
    return result


def _facility_to_code(facility_name: str, facility_map: Dict[str, str]) -> Optional[str]:
    """
    Legacy facility mapping rules:
    - 7161_x -> Sx
    - 9039_x -> Fx
    - 7037_x -> Rx
    - fallback to mapping_facility.txt
    """
    if facility_name.startswith("7161_"):
        return "S" + facility_name[5:]
    if facility_name.startswith("9039_"):
        return "F" + facility_name[5:]
    if facility_name.startswith("7037_"):
        return "R" + facility_name[5:]
    return facility_map.get(facility_name)


# ---------------------------------------------------------------------------
# ODI facility resolution
# ---------------------------------------------------------------------------

def _resolve_facility_sets(tt: TimetableData) -> Dict[str, List[str]]:
    """
    Build a map from ServiceFacilitySet[@id] → list of NeTEx facility names.
    Works for both inline ServiceFacilitySet and those in the shared file.
    """
    result: Dict[str, List[str]] = {}

    # Walk all loaded XML roots (shared file + all journey files)
    all_roots = []
    if tt.shared_root is not None:
        all_roots.append(tt.shared_root)
    all_roots.extend(tt.journey_roots)

    for root in all_roots:
        for sfs in root.iter(f"{{{NS}}}ServiceFacilitySet"):
            sfs_id = sfs.get("id", "")
            names: List[str] = []
            for child in sfs:
                local = _local_name(child.tag)
                text = (child.text or "").strip()
                if text and local != "keyList":
                    # SFS child elements may contain space-separated token lists
                    # (e.g. FareClasses="businessClass economyClass"); split each.
                    names.extend(text.split())

                # Legacy source also carries facility codes in keyList/KeyValue
                # where Key/Value should become e.g. 9039_28, 7161_46, 7037_11.
                if local == "keyList":
                    for kv in child.iter():
                        if _local_name(kv.tag) != "KeyValue":
                            continue
                        key = _child_text(kv, "Key")
                        val = _child_text(kv, "Value")
                        if key and val:
                            names.append(f"{key}_{val}")
            if sfs_id:
                result[sfs_id] = names
    return result


def _build_odis_for_train_legacy(
    train_id: int,
    sj: ET.Element,
    sfs_map: Dict[str, List[str]],
    facility_map: Dict[str, str],
    spijp_order: Dict[str, int],
    por_stop_numbers: List[int],
    brand_code: str,
    odi_id_counter: List[int],
) -> List[Odi]:
    """
    Legacy-compatible ODI behavior:
    - One ODI row per facility code occurrence (do not group)
    - Rxx -> reservation field, others -> tff_or_asd_or_ser field
    - Add one per-train fallback ODI row carrying brand in tariff_or_quantity
    """
    odis: List[Odi] = []
    if not por_stop_numbers:
        return odis

    default_to_stop_number = str(max(por_stop_numbers))

    journey_parts = sj.findall(f".//{{{NS}}}JourneyPart")
    for jp in journey_parts:
        from_stop_number, to_stop_number = _journeypart_stop_range(
            jp=jp,
            spijp_order=spijp_order,
            por_stop_numbers=por_stop_numbers,
        )
        fac_names: List[str] = []
        inline_sfs = jp.find(f"{{{NS}}}ServiceFacilitySet")
        if inline_sfs is not None:
            for child in inline_sfs:
                local = _local_name(child.tag)
                text = (child.text or "").strip()
                if text and local != "keyList":
                    fac_names.extend(text.split())
                if local == "keyList":
                    for kv in child.iter():
                        if _local_name(kv.tag) != "KeyValue":
                            continue
                        key = _child_text(kv, "Key")
                        val = _child_text(kv, "Value")
                        if key and val:
                            fac_names.append(f"{key}_{val}")
        else:
            ref_el = jp.find(f".//{{{NS}}}ServiceFacilitySetRef")
            if ref_el is not None:
                ref = ref_el.get("ref", "")
                fac_names = sfs_map.get(ref, [])

        for fac in fac_names:
            code = _facility_to_code(fac, facility_map)
            if not code:
                continue

            tff_or_asd_or_ser: Optional[str] = None
            reservation: Optional[str] = None
            if code.startswith("R"):
                reservation = code[1:]
            else:
                tff_or_asd_or_ser = code

            odi_id_counter[0] += 1
            odis.append(Odi(
                odi_id=odi_id_counter[0],
                train_id=train_id,
                from_stop_number=from_stop_number,
                to_stop_number=to_stop_number,
                tff_or_asd_or_ser=tff_or_asd_or_ser,
                reservation=reservation,
                equipment=None,
                tariff_or_quantity=None,
            ))

    # Legacy fallback row: emit a PDT segment carrying the brand code
    # (e.g. 101=nightRail) by routing it through Odi.equipment, which the
    # merits collector maps to PDT/brand_code (path 2_PRD/4_POP/9_ODI/PDT).
    if brand_code:
        odi_id_counter[0] += 1
        odis.append(Odi(
            odi_id=odi_id_counter[0],
            train_id=train_id,
            from_stop_number="1",
            to_stop_number=default_to_stop_number,
            tff_or_asd_or_ser=None,
            reservation=None,
            equipment=brand_code,
            tariff_or_quantity=None,
        ))

    return odis


def _build_odis_for_train(
    train_id: int,
    sj: ET.Element,
    sfs_map: Dict[str, List[str]],
    facility_map: Dict[str, str],
    spijp_order: Dict[str, int],
    por_stop_numbers: List[int],
    odi_id_counter: List[int],
    brand_code: str = "",
) -> List[Odi]:
    """
    Derive ODI records from JourneyPart ServiceFacilitySetRef.
    Each JourneyPart produces one ODI covering its from/to stops.
    Always produces a brand fallback ODI row (matching old converter behaviour).
    """
    odis: List[Odi] = []
    if not facility_map:
        return odis

    if not por_stop_numbers:
        return odis

    journey_parts = sj.findall(f".//{{{NS}}}JourneyPart")
    for jp in journey_parts:
        # Collect facility names — first try inline ServiceFacilitySet children,
        # then fall back to ServiceFacilitySetRef in shared file
        fac_names: List[str] = []
        inline_sfs = jp.find(f"{{{NS}}}ServiceFacilitySet")
        if inline_sfs is not None:
            for child in inline_sfs:
                tag = child.tag.split("}")[-1] if "}" in child.tag else child.tag
                text = (child.text or "").strip()
                if text:
                    fac_names.extend(text.split())
        else:
            ref_el = jp.find(f".//{{{NS}}}ServiceFacilitySetRef")
            if ref_el is not None:
                ref = ref_el.get("ref", "")
                fac_names = sfs_map.get(ref, [])

        if not fac_names:
            continue

        # Map facility names to MERITS codes
        # R-prefix (code list 7037, reservation) must go into Odi.reservation
        # as a subfield qualifier, NOT into tff_or_asd_or_ser (which is code list
        # 9039 for SER ser_code or 7161 for ASD asd_code).
        odi_codes: List[str] = []
        reservation: Optional[str] = None
        seen: set = set()
        for raw_code in (facility_map.get(n, "") for n in fac_names):
            if not raw_code or len(raw_code) < 2:
                continue
            prefix, num = raw_code[0], raw_code[1:]
            if prefix == "S":
                odi_code = f"S{num}"
                if odi_code not in seen:
                    odi_codes.append(odi_code)
                    seen.add(odi_code)
            elif prefix == "F":
                odi_code = f"F{num}"
                if odi_code not in seen:
                    odi_codes.append(odi_code)
                    seen.add(odi_code)
            elif prefix == "R" and reservation is None:
                reservation = num  # first R-code; attached as qualifier on each row

        if not odi_codes:
            continue

        # MERITS expects 1-based numeric stop positions within the train POR list.
        from_stop_number, to_stop_number = _journeypart_stop_range(
            jp=jp,
            spijp_order=spijp_order,
            por_stop_numbers=por_stop_numbers,
        )

        for odi_code in odi_codes:
            odi_id_counter[0] += 1
            odis.append(Odi(
                odi_id=odi_id_counter[0],
                train_id=train_id,
                from_stop_number=from_stop_number,
                to_stop_number=to_stop_number,
                tff_or_asd_or_ser=odi_code,
                reservation=None,
                equipment=None,
                tariff_or_quantity=None,
            ))

    # Brand fallback: always emit one ODI row covering the full train span.
    # The brand code (e.g. 101=nightRail, 92=regionalRail) is carried in
    # Odi.equipment, which the merits collector maps to PDT/brand_code
    # (path 2_PRD/4_POP/9_ODI/PDT).  This is required for service-brand-
    # gated rules in MERITS (e.g. sleeper configuration on brand 101).
    if brand_code:
        odi_id_counter[0] += 1
        odis.append(Odi(
            odi_id=odi_id_counter[0],
            train_id=train_id,
            from_stop_number="1",
            to_stop_number=str(max(por_stop_numbers)),
            tff_or_asd_or_ser=None,
            reservation=None,
            equipment=brand_code,
            tariff_or_quantity=None,
        ))

    return odis


# ---------------------------------------------------------------------------
# Batch converter
# ---------------------------------------------------------------------------

def convert_batch(
    source_dir: Path,
    station_zip: Path,
    output_file: Path,
    originator: str,
    config_dir: Path,
    station_pattern: str = "RailStations",
    legacy_upload_parity: bool = False,
) -> None:
    # Load configuration mappings
    brand_map = load_mapping(config_dir / "mapping_brand.txt")
    facility_map = load_mapping(config_dir / "mapping_facility.txt")
    service_mode_map = load_mapping(config_dir / "mapping_service_mode.txt")

    print(f"Configuration:")
    print(f"  brand_map:        {len(brand_map)} entries  {list(brand_map.items())[:3]}")
    print(f"  facility_map:     {len(facility_map)} entries  {list(facility_map.items())[:3]}")
    print(f"  service_mode_map: {len(service_mode_map)} entries  {list(service_mode_map.items())[:3]}")
    print(f"  legacy_upload_parity: {legacy_upload_parity}")

    # Build station index once, shared across all operators
    print(f"\nLoading station index from {station_zip.name} ...")
    _t0 = time.perf_counter()
    quay_index = _build_station_index(station_zip)
    print(f"  {len(quay_index)} quays indexed   [{time.perf_counter() - _t0:6.2f}s]")
    timings: Dict[str, float] = {"station_index": time.perf_counter() - _t0}
    per_operator: List[Dict[str, float]] = []

    # Find all timetable ZIPs (skip the station ZIP by pattern)
    timetable_zips = sorted([
        p for p in source_dir.glob("*.zip")
        if station_pattern.lower() not in p.name.lower()
        and "skdupd" not in p.name.lower()
        and "tsdupd" not in p.name.lower()
    ])
    if not timetable_zips:
        raise SystemExit(f"No timetable ZIPs found in {source_dir} (station pattern: {station_pattern!r})")

    print(f"\nFound {len(timetable_zips)} timetable ZIPs:")
    for z in timetable_zips:
        print(f"  {z.name}")

    # Global ID counters across all operators
    train_id_offset = 0
    por_id_offset = 0
    odi_id_counter = [0]

    all_meta: List[Meta] = []
    all_trains: List[Train] = []
    all_pors: List[Por] = []
    all_odis: List[Odi] = []

    today = date.today().isoformat()
    # MERITS expects `reference` to be a 15-char timestamp 'YYYY-MM-DDTHHMMSS'.
    # The HDR collector takes reference[:-2] for date_1 (qualifier 45).
    from datetime import datetime
    reference = datetime.now().strftime("%Y-%m-%dT%H%M%S")
    resolved_originator = resolve_originator(originator, None)
    print(f"Originator {originator!r} -> RICS {resolved_originator!r}")
    all_meta.append(Meta(
        reference=reference,
        validity_first_date=today,
        validity_last_date=today,
        originator=resolved_originator,
    ))

    for timetable_zip in timetable_zips:
        op_label = timetable_zip.name.split("_")[0].upper()
        print(f"\n--- Processing {timetable_zip.name} ({op_label}) ---")
        op_t0 = time.perf_counter()
        op_timings: Dict[str, float] = {"operator": op_label, "size_mb": timetable_zip.stat().st_size / 1_048_576}

        _t = time.perf_counter()
        tt = TimetableData(timetable_zip)
        op_timings["parse_zip"] = time.perf_counter() - _t
        print(f"  {len(tt.ssp_to_quay)} SSP->Quay | {len(tt.spijp_to_ssp)} StopPointsInJP "
              f"| {sum(len(v) for v in tt.dated_journeys_by_sj().values())} DSJs   [parse {op_timings['parse_zip']:6.2f}s]")

        _t = time.perf_counter()
        sj_list = list(tt.service_journeys())
        op_timings["sj_list"] = time.perf_counter() - _t

        # Legacy provider mapping from shared operators to RICS/company code.
        _t = time.perf_counter()
        operator_rics = _operator_rics_map(tt) if legacy_upload_parity else {}
        op_timings["operator_rics"] = time.perf_counter() - _t

        # Build facility set lookup from this operator's data (including shared file)
        _t = time.perf_counter()
        sfs_map = _resolve_facility_sets(tt)
        op_timings["facility_sets"] = time.perf_counter() - _t
        if sfs_map:
            print(f"  {len(sfs_map)} ServiceFacilitySets resolved   [{op_timings['facility_sets']:6.2f}s]")

        # build_trains_and_pors with global ID offsets and brand mapping
        _t = time.perf_counter()
        spijp_remap: Dict[int, Dict[str, int]] = {}
        train_sjs: List[ET.Element] = []
        _, op_trains, op_pors = build_trains_and_pors(
            tt=tt,
            quay_index=quay_index,
            originator=resolved_originator,
            brand_map=brand_map,
            service_mode_map=service_mode_map,
            train_id_offset=train_id_offset,
            por_id_offset=por_id_offset,
            spijp_remap_out=spijp_remap,
            train_sjs_out=train_sjs,
        )

        op_timings["build_trains_and_pors"] = time.perf_counter() - _t
        print(f"  {len(op_trains)} trains, {len(op_pors)} passage-or-record entries   [build {op_timings['build_trains_and_pors']:6.2f}s]")

        # Build ODI records: facility_map controls SER/ASD codes; brand fallback
        # is always generated when available regardless of SFS data.
        _odi_t = time.perf_counter()
        if facility_map:
            # Pre-bucket POR stop_numbers by train_id once (O(P)) instead of
            # filtering all PORs for every train (O(T*P)) inside the loop.
            por_by_train: Dict[int, List[str]] = {}
            for p in op_pors:
                por_by_train.setdefault(p.train_id, []).append(p.stop_number)

            for idx, train in enumerate(op_trains):
                sj = train_sjs[idx]
                por_stop_numbers = por_by_train.get(train.train_id, [])
                brand_code = ""
                submode = _service_submode_value(sj)
                if submode:
                    brand_code = brand_map.get(submode, "")

                if legacy_upload_parity:
                    odis = _build_odis_for_train_legacy(
                        train_id=train.train_id,
                        sj=sj,
                        sfs_map=sfs_map,
                        facility_map=facility_map,
                        spijp_order=spijp_remap.get(train.train_id, tt.spijp_order),
                        por_stop_numbers=por_stop_numbers,
                        brand_code=brand_code,
                        odi_id_counter=odi_id_counter,
                    )
                else:
                    odis = _build_odis_for_train(
                        train_id=train.train_id,
                        sj=sj,
                        sfs_map=sfs_map,
                        facility_map=facility_map,
                        spijp_order=spijp_remap.get(train.train_id, tt.spijp_order),
                        por_stop_numbers=por_stop_numbers,
                        odi_id_counter=odi_id_counter,
                        brand_code=brand_code,
                    )
                all_odis.extend(odis)

            if all_odis:
                print(f"  {odi_id_counter[0]} ODI records so far")

        # Update global offsets for the next operator
        train_id_offset = op_trains[-1].train_id if op_trains else train_id_offset
        por_id_offset = op_pors[-1].por_id if op_pors else por_id_offset

        # Post-adjust train fields for legacy compatibility.
        if legacy_upload_parity:
            for idx, train in enumerate(op_trains):
                sj = train_sjs[idx]
                op_ref = sj.find(f"{{{NS}}}OperatorRef")
                op_ref_val = op_ref.get("ref", "") if op_ref is not None else ""
                op_short = op_ref_val.split(":")[-1] if op_ref_val else ""
                if op_ref_val in operator_rics:
                    train.service_provider = operator_rics[op_ref_val]
                elif op_short in operator_rics:
                    train.service_provider = operator_rics[op_short]

                tm = sj.find(f"{{{NS}}}TransportMode")
                transport_mode = (tm.text or "").strip() if tm is not None else ""
                if transport_mode in service_mode_map:
                    train.service_mode = service_mode_map[transport_mode]

        op_timings["build_odis"] = time.perf_counter() - _odi_t
        op_timings["total"] = time.perf_counter() - op_t0
        per_operator.append(op_timings)
        print(f"  operator total {op_timings['total']:6.2f}s")

        all_trains.extend(op_trains)
        all_pors.extend(op_pors)

    print(f"\nTotal: {len(all_trains)} trains, {len(all_pors)} PORs, {len(all_odis)} ODIs")

    # Write EDIFACT
    _t = time.perf_counter()
    converter = CsvsToEdifact()
    converter.load({
        definition.META_FILE_NAME:     _rows(all_meta, Meta),
        definition.TRAIN_FILE_NAME:    _rows(all_trains, Train),
        definition.POR_FILE_NAME:      _rows(all_pors, Por),
        definition.RELATION_FILE_NAME: _rows([], Relation),
        definition.ODI_FILE_NAME:      _rows(all_odis, Odi),
    })
    timings["edifact_load"] = time.perf_counter() - _t

    _t = time.perf_counter()
    edifact_text = converter.get()
    timings["edifact_serialize"] = time.perf_counter() - _t

    _t = time.perf_counter()
    output_file.parent.mkdir(parents=True, exist_ok=True)
    output_file.write_text(edifact_text, encoding="utf-8")
    timings["write_file"] = time.perf_counter() - _t
    print(f"\nWritten SKDUPD EDIFACT to {output_file}")
    print(f"  File size: {output_file.stat().st_size:,} bytes")

    # Also produce a unix-timestamped .zip alongside the .r file (MERITS
    # submission convention).  Remove any older SKDUPD_*.zip in the same
    # directory first so the output folder does not accumulate stale archives
    # from previous runs.
    import zipfile
    out_dir = output_file.parent
    removed = 0
    for stale in out_dir.glob("SKDUPD_*.zip"):
        try:
            stale.unlink()
            removed += 1
        except OSError:
            pass
    if removed:
        print(f"Removed {removed} previous SKDUPD ZIP archive(s) from {out_dir}")
    zip_path = out_dir / f"SKDUPD_{int(time.time())}.zip"
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.write(output_file, arcname=output_file.name)
    print(f"Written SKDUPD ZIP to {zip_path} ({zip_path.stat().st_size:,} bytes)")

    # ----- Timing summary -----
    print("\n=== Timing summary ===")
    print(f"  station_index    : {timings['station_index']:7.2f}s")
    print(f"  edifact_load     : {timings['edifact_load']:7.2f}s")
    print(f"  edifact_serialize: {timings['edifact_serialize']:7.2f}s")
    print(f"  write_file       : {timings['write_file']:7.2f}s")
    print("\n  Per-operator breakdown:")
    print(f"  {'op':6s} {'size_MB':>8s} {'parse':>7s} {'sj_list':>8s} {'sfs':>6s} {'build':>7s} {'odi':>7s} {'total':>7s}")
    op_total = 0.0
    for r in per_operator:
        op_total += r["total"]
        print(f"  {r['operator']:6s} {r['size_mb']:8.2f} {r['parse_zip']:7.2f} {r['sj_list']:8.2f} "
              f"{r['facility_sets']:6.2f} {r['build_trains_and_pors']:7.2f} {r['build_odis']:7.2f} {r['total']:7.2f}")
    print(f"  {'TOTAL':6s} {'':>8s} {'':>7s} {'':>8s} {'':>6s} {'':>7s} {'':>7s} {op_total:7.2f}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="run_conversion",
        description="Batch multi-operator NeTEx → SKDUPD EDIFACT (one delivery).",
    )
    parser.add_argument(
        "--source-dir",
        default="Source",
        help="Folder containing operator timetable ZIPs (default: Source/).",
    )
    parser.add_argument(
        "--stations",
        default=None,
        help="Station ZIP. Auto-detected from --source-dir if omitted.",
    )
    parser.add_argument(
        "--output",
        default="NEW_SKDUPD/new_SKDUPD.r",
        help="Output EDIFACT file path (default: NEW_SKDUPD/new_SKDUPD.r).",
    )
    parser.add_argument(
        "--originator",
        default=None,
        help="Override EDIFACT ORG/3036 RICS code. Auto-derived from ParticipantRef when omitted.",
    )
    parser.add_argument(
        "--config-dir",
        default=None,
        help="Path to Configuration/ directory. Defaults to ./Configuration/.",
    )
    parser.add_argument(
        "--station-pattern",
        default="RailStations",
        help="Filename substring to identify the station ZIP (default: RailStations).",
    )
    parser.add_argument(
        "--legacy-upload-parity",
        action="store_true",
        help=(
            "Use legacy output semantics for provider/mode/ODI to better match "
            "historical uploads."
        ),
    )
    return parser


def main() -> None:
    args = _build_arg_parser().parse_args()

    source_dir = Path(args.source_dir)
    if not source_dir.exists():
        raise SystemExit(f"Source directory not found: {source_dir}")

    # Auto-detect station ZIP if not provided
    if args.stations:
        station_zip = Path(args.stations)
    else:
        candidates = sorted(source_dir.glob(f"*{args.station_pattern}*.zip"))
        if not candidates:
            raise SystemExit(
                f"No station ZIP matching '*{args.station_pattern}*.zip' found in {source_dir}. "
                f"Specify --stations explicitly."
            )
        station_zip = candidates[-1]  # newest if multiple
        print(f"Auto-detected station ZIP: {station_zip.name}")

    config_dir = Path(args.config_dir) if args.config_dir else DEFAULT_CONFIG_DIR

    convert_batch(
        source_dir=source_dir,
        station_zip=station_zip,
        output_file=Path(args.output),
        originator=args.originator,
        config_dir=config_dir,
        station_pattern=args.station_pattern,
        legacy_upload_parity=args.legacy_upload_parity,
    )


if __name__ == "__main__":
    main()
