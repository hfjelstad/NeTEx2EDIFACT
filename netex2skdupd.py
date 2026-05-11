# -*- coding: utf-8 -*-
"""
netex2skdupd.py  —  Mode 1: NeTEx timetable + station file → SKDUPD EDIFACT
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Converts a NeTEx timetable ZIP together with a station ZIP directly to a
SKDUPD EDIFACT file.

Lookup chain:
  ServiceJourney.PrivateCode          → Train.service_number
  DatedServiceJourney → OperatingDay  → Train.first_day / last_day / operation_days
  TimetabledPassingTime → SPiJP → SSP → station file PSA → Quay
                                       → parent StopPlace.PrivateCode → Por.uic
                                       → Quay.PublicCode              → Por.arrival/departure_platform

Usage:
  python netex2skdupd.py --timetable Source/timetable.zip
                         --stations  Source/stations.zip
                         --output    NEW_SKDUPD/new_SKDUPD.r

The originator (EDIFACT ORG/3036 RICS code) is derived automatically from
<ParticipantRef> in the NeTEx file. Use --originator to override.
"""

from __future__ import annotations

import argparse
import zipfile
import xml.etree.ElementTree as ET
from datetime import date, timedelta, datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from merits.skdupd.csv_model import Meta, Odi, Por, Relation, Train
from merits.skdupd.csvs_to_edifact import CsvsToEdifact
from merits.skdupd import definition

from netex_helpers import (
    NS,
    participant_ref,
    private_code,
    ref as netex_ref,
    rows_in_memory,
    text as netex_text,
    uic_code,
)

from edifact_mappings import resolve_originator


# ---------------------------------------------------------------------------
# Configuration mappings
# ---------------------------------------------------------------------------

def load_mapping(path: Path) -> Dict[str, str]:
    """
    Load a key:value mapping file from Configuration/.
    Lines starting with # are comments. Empty lines are ignored.
    """
    mapping: Dict[str, str] = {}
    if not path.exists():
        return mapping
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if ":" in line:
            key, _, value = line.partition(":")
            mapping[key.strip()] = value.split("#")[0].strip()
    return mapping


DEFAULT_CONFIG_DIR = Path(__file__).parent / "Configuration"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _tag(el) -> str:
    return el.tag.split("}")[-1] if "}" in el.tag else el.tag


def _text(element, tag: str) -> str:
    return netex_text(element, tag)


def _ref(element, tag: str) -> str:
    return netex_ref(element, tag)


def _private_code(element, type_attr: str) -> str:
    return private_code(element, type_attr)


def _rows(instances, cls):
    return rows_in_memory(instances, cls)


def _parse_time(t: str) -> Optional[str]:
    """Return HH:MM or None. Strips seconds."""
    if not t:
        return None
    return t[:5]  # HH:MM


def _operation_days_bitmask(dates: List[date], first: date, last: date) -> str:
    """Build binary bitmask string from first to last (inclusive)."""
    date_set = set(dates)
    days = (last - first).days + 1
    return "".join("1" if first + timedelta(days=i) in date_set else "0" for i in range(days))


def _traffic_restriction_code(for_boarding: bool, for_alighting: bool) -> Optional[str]:
    """
    Map ForBoarding/ForAlighting to EDIFACT traffic restriction code.
    
    Codes (EDIFACT standard):
    - None: Normal stop (both boarding and alighting allowed)
    - "2": Alighting only (no boarding)
    - "3": Boarding only (no alighting)
    - "4": No boarding or alighting (pass-through)
    """
    if not for_boarding and not for_alighting:
        return "4"  # Pass-through
    elif not for_boarding and for_alighting:
        return "2"  # Alighting only
    elif for_boarding and not for_alighting:
        return "3"  # Boarding only
    else:
        return None  # Normal stop


# ---------------------------------------------------------------------------
# Facility code resolution
# ---------------------------------------------------------------------------

_FACILITY_LIST_TAGS: Tuple[str, ...] = (
    "CateringFacilityList",
    "FareClasses",
    "MobilityFacilityList",
    "AccommodationFacilityList",
    "LuggageCarriageFacilityList",
    "PassengerCommsFacilityList",
    "ServiceReservationFacilityList",
)


def _get_fac_set_refs(element: ET.Element) -> List[str]:
    """Return ServiceFacilitySetRef/@ref values from ./facilities/ container or as direct children."""
    refs: List[str] = []
    fac_container = element.find(f"{{{NS}}}facilities")
    if fac_container is not None:
        for r in fac_container.findall(f"{{{NS}}}ServiceFacilitySetRef"):
            ref = r.get("ref", "")
            if ref:
                refs.append(ref)
    for r in element.findall(f"{{{NS}}}ServiceFacilitySetRef"):
        ref = r.get("ref", "")
        if ref:
            refs.append(ref)
    return refs


def _resolve_facility_codes(
    fac_set: ET.Element, facility_map: Dict[str, str]
) -> Tuple[List[str], Optional[str]]:
    """
    Read all facility list tokens from a ServiceFacilitySet element and map them.

    Returns:
      (odi_codes, reservation)

      odi_codes    — deduplicated list of "S{n}" or "F{n}" strings:
                       S{n}  → Odi.tff_or_asd_or_ser  → ASD+{n}  (code list 7161)
                       F{n}  → Odi.tff_or_asd_or_ser  → SER+{n}  (code list 9039)
      reservation  — numeric string from the first R-code found, or None.
                     Goes into Odi.reservation → ASD/SER reservation subfield
                     (code list 7037).  NOT emitted as a standalone segment.
    """
    odi_codes: List[str] = []
    reservation: Optional[str] = None
    seen: set = set()
    for tag in _FACILITY_LIST_TAGS:
        el = fac_set.find(f"{{{NS}}}{tag}")
        if el is None or not el.text:
            continue
        for token in el.text.split():
            raw = facility_map.get(token, "")
            if not raw or len(raw) < 2:
                continue
            prefix, num = raw[0], raw[1:]
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
                reservation = num  # first R-code wins; attached as qualifier
    return odi_codes, reservation


# ---------------------------------------------------------------------------
# Station file index
# ---------------------------------------------------------------------------

def _uic_from_stop_place(sp) -> str:
    """Extract UIC code from a StopPlace element (typed PrivateCode only)."""
    return uic_code(sp, accept_legacy=False)


def _build_station_index(station_zip: Path) -> Dict[str, Tuple[str, str]]:
    """
    Returns quay_id → (uic_code, platform_public_code)
    by reading StopPlace UIC and nested Quay/PublicCode from station zip.
    """
    index: Dict[str, Tuple[str, str]] = {}
    with zipfile.ZipFile(station_zip) as z:
        xml_names = [n for n in z.namelist() if n.endswith(".xml")]
        for xml_name in xml_names:
            root = ET.fromstring(z.read(xml_name))
            for sp in root.findall(f".//{{{NS}}}StopPlace"):
                uic = _uic_from_stop_place(sp)
                if not uic:
                    continue
                for quay in sp.findall(f".//{{{NS}}}Quay"):
                    q_id = quay.get("id", "")
                    pub = quay.find(f"{{{NS}}}PublicCode")
                    platform = pub.text.strip() if pub is not None and pub.text else ""
                    if q_id:
                        index[q_id] = (uic, platform)
    return index


# ---------------------------------------------------------------------------
# Timetable parsing
# ---------------------------------------------------------------------------

class TimetableData:
    """Parses a NeTEx timetable ZIP (shared file + one or more journey files)."""

    def __init__(self, timetable_zip: Path):
        self.shared_root: Optional[ET.Element] = None
        self.journey_roots: List[ET.Element] = []
        self._load(timetable_zip)

        # Lookups built from shared file
        self.ssp_to_quay: Dict[str, str] = {}          # SSP id → Quay id
        self.od_to_date: Dict[str, date] = {}           # OperatingDay id → date
        self._build_shared_lookups()

        # Lookups built from journey files
        self.spijp_to_ssp: Dict[str, str] = {}          # SPiJP id → SSP id
        self.spijp_order: Dict[str, int] = {}            # SPiJP id → stop_number
        self.spijp_restrictions: Dict[str, Tuple[bool, bool]] = {}  # SPiJP id → (ForBoarding, ForAlighting)
        self._build_journey_lookups()

        # Facility sets (indexed from all loaded files)
        self.facility_sets: Dict[str, ET.Element] = {}
        self._build_facility_index()

    def _load(self, timetable_zip: Path) -> None:
        with zipfile.ZipFile(timetable_zip) as z:
            xml_names = [n for n in z.namelist() if n.endswith(".xml")]
            for name in xml_names:
                root = ET.fromstring(z.read(name))
                if "Shared" in name or "shared" in name or name.startswith("_"):
                    self.shared_root = root
                else:
                    self.journey_roots.append(root)
        if self.shared_root is None and self.journey_roots:
            # Fallback: treat first file as shared if no explicit shared file
            self.shared_root = self.journey_roots.pop(0)

    def _build_shared_lookups(self) -> None:
        root = self.shared_root

        # PSA: SSP → Quay
        for psa in root.findall(f".//{{{NS}}}PassengerStopAssignment"):
            ssp_ref = psa.find(f"{{{NS}}}ScheduledStopPointRef")
            quay_ref = psa.find(f"{{{NS}}}QuayRef")
            if ssp_ref is not None and quay_ref is not None:
                self.ssp_to_quay[ssp_ref.get("ref", "")] = quay_ref.get("ref", "")

        # OperatingDay: id → CalendarDate
        for od in root.findall(f".//{{{NS}}}OperatingDay"):
            od_id = od.get("id", "")
            cd = od.find(f"{{{NS}}}CalendarDate")
            if od_id and cd is not None and cd.text:
                try:
                    self.od_to_date[od_id] = date.fromisoformat(cd.text[:10])
                except ValueError:
                    pass

    def _build_journey_lookups(self) -> None:
        for root in self.journey_roots:
            for jp in root.findall(f".//{{{NS}}}JourneyPattern"):
                for order, spijp in enumerate(
                    jp.findall(f".//{{{NS}}}StopPointInJourneyPattern"), start=1
                ):
                    spijp_id = spijp.get("id", "")
                    ssp_ref = spijp.find(f"{{{NS}}}ScheduledStopPointRef")
                    ssp_id = ssp_ref.get("ref", "") if ssp_ref is not None else ""
                    
                    # Extract boarding/alighting restrictions (default to True if not specified)
                    for_boarding_el = spijp.find(f"{{{NS}}}ForBoarding")
                    for_alighting_el = spijp.find(f"{{{NS}}}ForAlighting")
                    for_boarding = for_boarding_el.text.lower() != "false" if for_boarding_el is not None and for_boarding_el.text else True
                    for_alighting = for_alighting_el.text.lower() != "false" if for_alighting_el is not None and for_alighting_el.text else True
                    
                    if spijp_id:
                        self.spijp_to_ssp[spijp_id] = ssp_id
                        self.spijp_order[spijp_id] = order
                        self.spijp_restrictions[spijp_id] = (for_boarding, for_alighting)

    def _build_facility_index(self) -> None:
        """Index all ServiceFacilitySet elements by id across shared and journey files."""
        all_roots = ([self.shared_root] if self.shared_root is not None else []) + self.journey_roots
        for root in all_roots:
            for fac in root.findall(f".//{{{NS}}}ServiceFacilitySet"):
                fac_id = fac.get("id", "")
                if fac_id:
                    self.facility_sets[fac_id] = fac

    def service_journeys(self):
        """Yield all ServiceJourney elements from journey files."""
        for root in self.journey_roots:
            yield from root.findall(f".//{{{NS}}}ServiceJourney")

    def dated_journeys_by_sj(self) -> Dict[str, List[date]]:
        """Map ServiceJourney id → sorted list of operating dates via DatedServiceJourney."""
        sj_dates: Dict[str, List[date]] = {}
        for root in self.journey_roots:
            for dsj in root.findall(f".//{{{NS}}}DatedServiceJourney"):
                sj_ref = dsj.find(f"{{{NS}}}ServiceJourneyRef")
                od_ref = dsj.find(f"{{{NS}}}OperatingDayRef")
                if sj_ref is None:
                    continue
                sj_id = sj_ref.get("ref", "")
                run_date: Optional[date] = None
                if od_ref is not None:
                    run_date = self.od_to_date.get(od_ref.get("ref", ""))
                if sj_id and run_date is not None:
                    sj_dates.setdefault(sj_id, []).append(run_date)
        for dates in sj_dates.values():
            dates.sort()
        return sj_dates


# ---------------------------------------------------------------------------
# Shared conversion logic
# ---------------------------------------------------------------------------

def build_trains_and_pors(
    tt: TimetableData,
    quay_index: Dict[str, Tuple[str, str]],
    originator: str,
    brand_map: Optional[Dict[str, str]] = None,
    facility_map: Optional[Dict[str, str]] = None,
    train_id_offset: int = 0,
    por_id_offset: int = 0,
) -> Tuple[List[Meta], List[Train], List[Por], List[Odi]]:
    """
    Convert parsed timetable + quay index into MERITS dataclass instances.
    Shared between the direct (netex2skdupd) and CSV-intermediate (netex2skdupd_csv) paths.

    train_id_offset / por_id_offset allow merging multiple operator files into
    one delivery with globally unique IDs.
    brand_map maps TransportSubmode value → MERITS service_mode code.
    """
    today = date.today().isoformat()
    meta_list = [Meta(
        reference=f"SKDUPD_{today}",
        validity_first_date=today,
        validity_last_date=None,
        originator=originator,
    )]

    trains: List[Train] = []
    pors: List[Por] = []
    odis: List[Odi] = []
    train_id = train_id_offset
    por_id = por_id_offset
    odi_id = 0
    skipped_stops = 0
    restricted_stops = 0  # Count stops with boarding/alighting restrictions

    sj_dates = tt.dated_journeys_by_sj()

    for sj in tt.service_journeys():
        sj_id = sj.get("id", "")
        # NeTEx 2.0: trainNumber lives in <privateCodes>/<PrivateCode type="trainNumber">
        # Fallback to legacy direct-child <PrivateCode>, then to sj_id.
        train_number = (
            _private_code(sj, "trainNumber")
            or _text(sj, "PrivateCode")
            or sj_id
        )

        # Operator code from OperatorRef (e.g. 'NSB:Operator:NSB' → 'NSB')
        op_ref_el = sj.find(f"{{{NS}}}OperatorRef")
        operator = op_ref_el.get("ref", "").split(":")[-1] if op_ref_el is not None else originator

        # Service mode from TransportSubmode via brand_map
        submode_el = sj.find(f".//{{{NS}}}TransportSubmode")
        service_mode: Optional[str] = None
        if submode_el is not None:
            for child in submode_el:
                submode_value = child.text or ""
                if brand_map and submode_value in brand_map:
                    service_mode = brand_map[submode_value]
                    break

        # Operating dates — from DatedServiceJourney (required)
        dates = sj_dates.get(sj_id, [])

        first_day = dates[0].isoformat() if dates else None
        last_day = dates[-1].isoformat() if dates else None
        op_days = _operation_days_bitmask(dates, dates[0], dates[-1]) if dates else None

        train_id += 1
        trains.append(Train(
            train_id=train_id,
            service_number=train_number,
            reservation=None,
            tariff=None,
            service_mode=service_mode,
            service_name=None,
            service_provider=operator,
            information_provider=None,
            reservation_company=None,
            first_day=first_day,
            last_day=last_day,
            operation_days=op_days,
            second_service_number=None,
        ))

        passing_times = sj.findall(f".//{{{NS}}}TimetabledPassingTime")

        def stop_order(tp):
            spijp_ref = tp.find(f"{{{NS}}}StopPointInJourneyPatternRef")
            ref = spijp_ref.get("ref", "") if spijp_ref is not None else ""
            return tt.spijp_order.get(ref, 999)

        passing_times_sorted = sorted(passing_times, key=stop_order)

        ssp_to_stop_num: Dict[str, int] = {}  # SSP id → 1-based stop position (for JourneyPart range resolution)

        for stop_num, tp in enumerate(passing_times_sorted, start=1):
            spijp_ref_el = tp.find(f"{{{NS}}}StopPointInJourneyPatternRef")
            spijp_ref = spijp_ref_el.get("ref", "") if spijp_ref_el is not None else ""
            ssp_id = tt.spijp_to_ssp.get(spijp_ref, "")
            if ssp_id:
                ssp_to_stop_num[ssp_id] = stop_num
            quay_id = tt.ssp_to_quay.get(ssp_id, "")
            uic, platform = quay_index.get(quay_id, ("", ""))

            if not uic:
                skipped_stops += 1

            arr = _parse_time(_text(tp, "ArrivalTime"))
            dep = _parse_time(_text(tp, "DepartureTime"))

            if stop_num == 1:
                arr = None
            if stop_num == len(passing_times_sorted):
                dep = None

            # Resolve boarding/alighting restrictions
            for_boarding, for_alighting = tt.spijp_restrictions.get(spijp_ref, (True, True))
            traffic_code = _traffic_restriction_code(for_boarding, for_alighting)
            if traffic_code is not None:
                restricted_stops += 1

            por_id += 1
            pors.append(Por(
                por_id=por_id,
                train_id=train_id,
                stop_number=stop_num,
                uic=uic or None,
                arrival_time=arr,
                arrival_time_offset=None,
                departure_time=dep,
                departure_time_offset=None,
                arrival_platform=platform or None,
                departure_platform=platform or None,
                property=None,
                traffic_restriction_code=traffic_code,
                distance_and_unit=None,
                loading_vehicles=None,
                unloading_vehicles=None,
                check_out=None,
                check_in=None,
            ))

        # --- Facility sets → ODI rows ---
        total_stops = len(passing_times_sorted)
        if facility_map and total_stops > 0:
            # JourneyPart-level facility sets (per-segment stop range)
            for jp in sj.findall(f".//{{{NS}}}JourneyPart"):
                jp_fac_ids = _get_fac_set_refs(jp)
                if not jp_fac_ids:
                    continue
                from_ssp_el = jp.find(f"{{{NS}}}FromStopPointRef")
                to_ssp_el = jp.find(f"{{{NS}}}ToStopPointRef")
                from_ssp = from_ssp_el.get("ref", "") if from_ssp_el is not None else ""
                to_ssp = to_ssp_el.get("ref", "") if to_ssp_el is not None else ""
                from_num = ssp_to_stop_num.get(from_ssp, 1)
                to_num = ssp_to_stop_num.get(to_ssp, total_stops)
                for fac_id in jp_fac_ids:
                    fac_el = tt.facility_sets.get(fac_id)
                    if fac_el is None:
                        continue
                    odi_codes, reservation = _resolve_facility_codes(fac_el, facility_map)
                    for edi_code in odi_codes:
                        odi_id += 1
                        odis.append(Odi(
                            odi_id=odi_id,
                            train_id=train_id,
                            from_stop_number=str(from_num),
                            to_stop_number=str(to_num),
                            tff_or_asd_or_ser=edi_code,
                        ))
            # SJ-level facility set (whole train)
            for fac_id in _get_fac_set_refs(sj):
                fac_el = tt.facility_sets.get(fac_id)
                if fac_el is None:
                    continue
                odi_codes, reservation = _resolve_facility_codes(fac_el, facility_map)
                for edi_code in odi_codes:
                    odi_id += 1
                    odis.append(Odi(
                        odi_id=odi_id,
                        train_id=train_id,
                        from_stop_number="1",
                        to_stop_number=str(total_stops),
                        tff_or_asd_or_ser=edi_code,

                    ))

    print(f"Converted {len(trains)} trains, {len(pors)} stop-times "
          f"({skipped_stops} stops without UIC, {restricted_stops} with restrictions), "
          f"{len(odis)} ODI facility entries")
    return meta_list, trains, pors, odis


# ---------------------------------------------------------------------------
# Conversion
# ---------------------------------------------------------------------------

def convert(
    timetable_zip: Path,
    station_zip: Path,
    output_file: Path,
    originator: str | None = None,
    config_dir: Optional[Path] = None,
) -> None:
    cfg_dir = config_dir or DEFAULT_CONFIG_DIR
    brand_map = load_mapping(cfg_dir / "mapping_brand.txt")
    if brand_map:
        print(f"  Loaded brand map: {len(brand_map)} entries")
    facility_map = load_mapping(cfg_dir / "mapping_facility.txt")
    if facility_map:
        print(f"  Loaded facility map: {len(facility_map)} entries")

    print(f"Loading station index from {station_zip.name} ...")
    quay_index = _build_station_index(station_zip)
    print(f"  {len(quay_index)} quays indexed")

    print(f"Parsing timetable from {timetable_zip.name} ...")
    tt = TimetableData(timetable_zip)
    print(f"  {len(tt.ssp_to_quay)} SSP→Quay assignments")
    print(f"  {len(tt.spijp_to_ssp)} StopPointInJourneyPattern entries")
    print(f"  {sum(len(v) for v in tt.dated_journeys_by_sj().values())} DatedServiceJourney entries")

    # Resolve originator: CLI override > ParticipantRef in NeTEx file
    participant = participant_ref(tt.shared_root) if tt.shared_root is not None else ""
    resolved_originator = resolve_originator(participant, originator)
    print(f"  Originator: {resolved_originator!r} (ParticipantRef={participant!r})")

    meta_list, trains, pors, odis = build_trains_and_pors(tt, quay_index, resolved_originator, brand_map=brand_map, facility_map=facility_map)

    converter = CsvsToEdifact()
    converter.load({
        definition.META_FILE_NAME:     _rows(meta_list, Meta),
        definition.TRAIN_FILE_NAME:    _rows(trains, Train),
        definition.POR_FILE_NAME:      _rows(pors, Por),
        definition.RELATION_FILE_NAME: _rows([], Relation),
        definition.ODI_FILE_NAME:      _rows(odis, Odi),
    })
    edifact_text = converter.get()

    output_file.parent.mkdir(parents=True, exist_ok=True)
    output_file.write_text(edifact_text, encoding="utf-8")
    print(f"Written SKDUPD EDIFACT to {output_file}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="netex2skdupd",
        description="Convert NeTEx timetable + station file to SKDUPD EDIFACT.",
    )
    parser.add_argument(
        "--timetable",
        required=True,
        help="Path to timetable NeTEx ZIP.",
    )
    parser.add_argument(
        "--stations",
        required=True,
        help="Path to station NeTEx ZIP.",
    )
    parser.add_argument(
        "--output",
        default="./NEW_SKDUPD/new_SKDUPD.r",
    )
    parser.add_argument(
        "--originator",
        default=None,
        help="Override EDIFACT ORG/3036 RICS code. Auto-derived from ParticipantRef when omitted.",
    )
    return parser


def main() -> None:
    args = _build_arg_parser().parse_args()
    convert(
        timetable_zip=Path(args.timetable),
        station_zip=Path(args.stations),
        output_file=Path(args.output),
        originator=args.originator,
    )


if __name__ == "__main__":
    main()
