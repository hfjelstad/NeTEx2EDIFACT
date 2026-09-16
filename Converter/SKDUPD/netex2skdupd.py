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

import sys
from pathlib import Path
# Ensure the project root is on sys.path when this script is run directly
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import argparse
import logging
import zipfile
import xml.etree.ElementTree as ET
from datetime import date, timedelta, datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from merits.skdupd.csv_model import Meta, Odi, Por, Relation, Train
from merits.skdupd.csvs_to_edifact import CsvsToEdifact
from merits.skdupd import definition

from Converter.Shared.netex_helpers import (
    NS,
    participant_ref,
    private_code,
    ref as netex_ref,
    rows_in_memory,
    text as netex_text,
    uic_code,
)
from Converter.Shared.edifact_mappings import PARTICIPANT_TO_RICS, resolve_originator


logger = logging.getLogger(__name__)


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


# Configuration/ lives at the project root (NeTEx2EDIFACT/), not next to this
# module. Resolve it relative to this file's grand-grand-parent.
DEFAULT_CONFIG_DIR = Path(__file__).resolve().parents[2] / "Configuration"


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
    """Return HHMM (4-digit numeric) or None. Strips seconds and colon.

    MERITS POR/E362 expects time as a 4-digit numeric value (data element 2002),
    not the ISO HH:MM form.  '09:30:00' -> '0930'.
    """
    if not t:
        return None
    s = t[:5]  # HH:MM
    if len(s) == 5 and s[2] == ":":
        return s[:2] + s[3:]
    return s.replace(":", "")


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
    - "1": Boarding only (no alighting) → MERITS code Z
    - "2": Alighting only (no boarding) → MERITS code A
    - "4": No boarding or alighting (pass-through)
    """
    if not for_boarding and not for_alighting:
        return "4"  # Pass-through
    elif not for_boarding and for_alighting:
        return "2"  # Alighting only
    elif for_boarding and not for_alighting:
        return "1"  # Boarding only
    else:
        return None  # Normal stop


# ---------------------------------------------------------------------------
# Station file index
# ---------------------------------------------------------------------------

def _uic_from_stop_place(sp) -> str:
    """Extract UIC code from a StopPlace element.

    Priority:
      1. privateCodes/PrivateCode[@type='uicCode']  (NeTEx standard)
      2. keyList/KeyValue with Key='iffCode'        (NSR fallback for Swedish stations)
    """
    code = uic_code(sp, accept_legacy=False)
    if code:
        return code
    # Fallback: NSR stores some UIC codes as iffCode in keyList
    for kv in sp.findall(f"{{{NS}}}keyList/{{{NS}}}KeyValue"):
        key_el = kv.find(f"{{{NS}}}Key")
        val_el = kv.find(f"{{{NS}}}Value")
        if key_el is not None and (key_el.text or "").strip() == "iffCode":
            val = (val_el.text or "").strip() if val_el is not None else ""
            if val:
                return val
    return ""


def _build_station_index(station_path: Path) -> Dict[str, Tuple[str, str]]:
    """
    Returns quay_id → (uic_code, platform_public_code)
    by reading StopPlace UIC and nested Quay/PublicCode from a station NeTEx
    source.  Accepts either a ZIP archive of XML files or a single .xml
    document.

    Child StopPlaces (those with a ParentSiteRef) inherit the parent's UIC
    code when their own privateCodes/uicCode is empty.  This pattern is
    used in the cross-border Tiamat export for Swedish/Danish stations.
    """
    index: Dict[str, Tuple[str, str]] = {}

    def _index_root(root: ET.Element) -> None:
        # First pass: build {stop_place_id: uic} and {stop_place_id: parent_id}
        own_uic: Dict[str, str] = {}
        parent_of: Dict[str, str] = {}
        stop_places = root.findall(f".//{{{NS}}}StopPlace")
        for sp in stop_places:
            sp_id = sp.get("id", "")
            if not sp_id:
                continue
            u = _uic_from_stop_place(sp)
            if u:
                own_uic[sp_id] = u
            parent_el = sp.find(f"{{{NS}}}ParentSiteRef")
            if parent_el is not None:
                pref = parent_el.get("ref", "")
                if pref:
                    parent_of[sp_id] = pref

        def _resolve_uic(sp_id: str) -> str:
            seen: set = set()
            cur = sp_id
            while cur and cur not in seen:
                seen.add(cur)
                if cur in own_uic:
                    return own_uic[cur]
                cur = parent_of.get(cur, "")
            return ""

        # Second pass: index quays using inherited UIC where needed.
        for sp in stop_places:
            sp_id = sp.get("id", "")
            uic = _resolve_uic(sp_id)
            if not uic:
                continue
            for quay in sp.findall(f".//{{{NS}}}Quay"):
                q_id = quay.get("id", "")
                pub = quay.find(f"{{{NS}}}PublicCode")
                platform = pub.text.strip() if pub is not None and pub.text else ""
                if q_id:
                    index[q_id] = (uic, platform)

    suffix = station_path.suffix.lower()
    if suffix == ".zip":
        with zipfile.ZipFile(station_path) as z:
            for xml_name in (n for n in z.namelist() if n.endswith(".xml")):
                _index_root(ET.fromstring(z.read(xml_name)))
    elif suffix == ".xml":
        _index_root(ET.parse(str(station_path)).getroot())
    else:
        raise SystemExit(f"Unsupported station file extension: {station_path.suffix} ({station_path})")
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

    def service_journeys(self):
        """Yield all ServiceJourney elements from journey files."""
        for root in self.journey_roots:
            yield from root.findall(f".//{{{NS}}}ServiceJourney")

    def dated_journeys_by_sj(self) -> Dict[str, List[date]]:
        """Map ServiceJourney id → sorted list of operating dates via DatedServiceJourney.

        DatedServiceJourneys with ServiceAlteration 'cancellation' or 'replaced'
        are excluded — those dates indicate that the base service does NOT run.
        """
        sj_dates: Dict[str, List[date]] = {}
        _excluded_alterations = {"cancellation", "replaced"}
        for root in self.journey_roots:
            for dsj in root.findall(f".//{{{NS}}}DatedServiceJourney"):
                # Skip dates where the service is cancelled or replaced
                alteration_el = dsj.find(f"{{{NS}}}ServiceAlteration")
                if alteration_el is not None and (alteration_el.text or "").strip().lower() in _excluded_alterations:
                    continue
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

def _resolve_journey_stops(
    sj: ET.Element,
    tt: TimetableData,
    quay_index: Dict[str, Tuple[str, str]],
) -> Tuple[List[Tuple[str, ET.Element, str, str]], int]:
    """Resolve one ServiceJourney's passing times to UIC-bearing stops.

    Returns ``(emitted, skipped)`` where ``emitted`` is the stop-ordered list
    of ``(spijp_ref, passing_time, uic, platform)`` tuples and ``skipped`` is
    the number of passing times dropped for lacking a UIC code.  MERITS
    POR/E517(1)/3225 requires a UIC, and ODI/1050 refs depend on the
    renumbered sequence, so stops without UIC cannot be represented.
    """
    passing_times = sj.findall(f".//{{{NS}}}TimetabledPassingTime")

    def stop_order(tp):
        spijp_ref = tp.find(f"{{{NS}}}StopPointInJourneyPatternRef")
        ref = spijp_ref.get("ref", "") if spijp_ref is not None else ""
        return tt.spijp_order.get(ref, 999)

    emitted: List[Tuple[str, ET.Element, str, str]] = []
    skipped = 0
    for tp in sorted(passing_times, key=stop_order):
        spijp_ref_el = tp.find(f"{{{NS}}}StopPointInJourneyPatternRef")
        spijp_ref = spijp_ref_el.get("ref", "") if spijp_ref_el is not None else ""
        ssp_id = tt.spijp_to_ssp.get(spijp_ref, "")
        quay_id = tt.ssp_to_quay.get(ssp_id, "")
        uic, platform = quay_index.get(quay_id, ("", ""))
        if not uic:
            skipped += 1
            continue
        emitted.append((spijp_ref, tp, uic, platform))
    return emitted, skipped


def _build_pors_for_train(
    emitted: List[Tuple[str, ET.Element, str, str]],
    train_id: int,
    por_id: int,
    tt: TimetableData,
) -> Tuple[List[Por], int, int]:
    """Build the POR rows for a single train.

    ``por_id`` is the last id used so far; the first emitted POR takes
    ``por_id + 1``.  Returns ``(pors, next_por_id, restricted_stops)``.

    Day-offset emission (POR/E362 sub-element 4, e.g. ":::1") is written ONLY
    on the first arrival/departure that crosses midnight — matching validated
    reference output; the validator infers the rollover for later stops.
    """
    pors: List[Por] = []
    restricted_stops = 0
    total_stops = len(emitted)
    prev_offset = "0"
    first_marker_emitted = False
    for stop_num, (spijp_ref, tp, uic, platform) in enumerate(emitted, start=1):
        arr = _parse_time(_text(tp, "ArrivalTime"))
        dep = _parse_time(_text(tp, "DepartureTime"))
        arr_off_raw = (_text(tp, "ArrivalDayOffset") or "0").strip() or "0"
        dep_off_raw = (_text(tp, "DepartureDayOffset") or "0").strip() or "0"

        # Bus/coach passing times often carry only one of arrival/departure.
        # Mirror the present value (with its day-offset) so intermediate stops
        # show a time and a shortened journey's terminus is not misread as a
        # run-through (empty POR) once the departure is dropped below.
        if arr is None and dep is not None:
            arr, arr_off_raw = dep, dep_off_raw
        elif dep is None and arr is not None:
            dep, dep_off_raw = arr, arr_off_raw

        # Mark only the first arrival/departure that increases the
        # cumulative day-offset relative to the previous emitted offset.
        arr_off: Optional[str] = None
        dep_off: Optional[str] = None
        if not first_marker_emitted and arr is not None and arr_off_raw != prev_offset:
            arr_off = arr_off_raw
            first_marker_emitted = True
            prev_offset = arr_off_raw
        elif not first_marker_emitted and dep is not None and dep_off_raw != prev_offset:
            dep_off = dep_off_raw
            first_marker_emitted = True
            prev_offset = dep_off_raw
        elif dep_off_raw != prev_offset and first_marker_emitted:
            # Multi-day journeys (rare): emit subsequent rollover too.
            dep_off = dep_off_raw
            prev_offset = dep_off_raw

        if stop_num == 1:
            arr = None
            arr_off = None
        if stop_num == total_stops:
            dep = None
            dep_off = None

        for_boarding, for_alighting = tt.spijp_restrictions.get(spijp_ref, (True, True))
        traffic_code = _traffic_restriction_code(for_boarding, for_alighting)
        if traffic_code is not None:
            restricted_stops += 1

        por_id += 1
        pors.append(Por(
            por_id=por_id,
            train_id=train_id,
            stop_number=stop_num,
            uic=uic,
            arrival_time=arr,
            arrival_time_offset=arr_off,
            departure_time=dep,
            departure_time_offset=dep_off,
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
    return pors, por_id, restricted_stops


def _log_conversion_summary(
    trains: List[Train],
    pors: List[Por],
    *,
    skipped_stops: int,
    restricted_stops: int,
    skipped_trains: int,
    converted_by_mode: Dict[str, int],
    skipped_by_mode: Dict[str, int],
    skipped_rail_details: List[Tuple[str, str, int, int]],
) -> None:
    """Emit the human-readable conversion summary via the module logger."""
    non_rail_skipped = sum(n for m, n in skipped_by_mode.items() if m != "rail")
    non_rail_converted = sum(n for m, n in converted_by_mode.items() if m != "rail")
    unit = "journeys" if non_rail_converted else "trains"
    logger.info(
        "Converted %d %s, %d stop-times (%d stops without UIC, %d with restrictions%s)",
        len(trains), unit, len(pors), skipped_stops, restricted_stops,
        f", {skipped_trains} rail journeys skipped (<2 valid stops)" if skipped_trains else "",
    )
    if non_rail_converted:
        conv_breakdown = ", ".join(
            f"{m}={n}" for m, n in sorted(converted_by_mode.items(), key=lambda kv: -kv[1])
        )
        logger.info("  Converted by mode: %s", conv_breakdown)
    if non_rail_skipped:
        skip_breakdown = ", ".join(
            f"{m}={n}" for m, n in sorted(skipped_by_mode.items(), key=lambda kv: -kv[1]) if m != "rail"
        )
        logger.info("  Skipped non-rail modes: %s", skip_breakdown)
    if skipped_rail_details:
        rail_n = len(skipped_rail_details)
        logger.warning(
            "%d rail journey(s) skipped due to <2 UIC-resolvable stops:", rail_n
        )
        for sj_id, train_number, total_pt, valid in skipped_rail_details[:20]:
            logger.warning(
                "    train#%8s  %d/%d stops with UIC  (%s)",
                train_number, valid, total_pt, sj_id,
            )
        if rail_n > 20:
            logger.warning("    ... and %d more (showing first 20)", rail_n - 20)


def build_trains_and_pors(
    tt: TimetableData,
    quay_index: Dict[str, Tuple[str, str]],
    originator: str,
    brand_map: Optional[Dict[str, str]] = None,
    train_id_offset: int = 0,
    por_id_offset: int = 0,
    service_mode_map: Optional[Dict[str, str]] = None,
    spijp_remap_out: Optional[Dict[int, Dict[str, int]]] = None,
    train_sjs_out: Optional[List[ET.Element]] = None,
) -> Tuple[List[Meta], List[Train], List[Por]]:
    """
    Convert parsed timetable + quay index into MERITS dataclass instances.
    Shared between the direct (netex2skdupd) and CSV-intermediate (netex2skdupd_csv) paths.

    train_id_offset / por_id_offset allow merging multiple operator files into
    one delivery with globally unique IDs.
    brand_map maps TransportSubmode value → MERITS service_mode code.

    spijp_remap_out, when provided, is populated with one entry per emitted
    train: ``{train_id: {spijp_ref: new_stop_number, ...}, ...}`` so callers
    (such as ODI builders) can translate SPiJP refs into the renumbered POR
    sequence after stops without UIC have been dropped.

    train_sjs_out, when provided, is appended with the source ServiceJourney
    element for every emitted Train (parallel to the returned trains list),
    since journeys with fewer than two UIC-resolvable stops are skipped.
    """
    today = date.today().isoformat()
    # MERITS expects `reference` to be a 15-char timestamp 'YYYY-MM-DDTHHMMSS'.
    # The HDR collector takes reference[:-2] for date_1 (qualifier 45).
    reference = datetime.now().strftime("%Y-%m-%dT%H%M%S")
    meta_list = [Meta(
        reference=reference,
        validity_first_date=today,
        validity_last_date=today,
        originator=originator,
    )]

    trains: List[Train] = []
    pors: List[Por] = []
    train_id = train_id_offset
    por_id = por_id_offset
    skipped_stops = 0
    skipped_trains = 0
    restricted_stops = 0  # Count stops with boarding/alighting restrictions

    # Per-TransportMode breakdown so dropped rail journeys (which usually
    # indicate genuine data problems) can be distinguished from skipped
    # buses or coaches (which are expected for SKDUPD).
    skipped_by_mode: Dict[str, int] = {}
    converted_by_mode: Dict[str, int] = {}
    skipped_rail_details: List[Tuple[str, str, int, int]] = []  # (sj_id, train_number, total_pt, valid_stops)

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
        operator_alpha = op_ref_el.get("ref", "").split(":")[-1] if op_ref_el is not None else originator
        # PRD/3036(1) requires a RICS code, not an alpha code.
        operator = PARTICIPANT_TO_RICS.get(operator_alpha.upper(), originator)

        # PRD/E989(1)/7009 service_mode = transport mode code (e.g. rail → 37)
        tm_el = sj.find(f"{{{NS}}}TransportMode")
        tm_value = (tm_el.text or "").strip() if tm_el is not None else ""
        service_mode: Optional[str] = None
        if service_mode_map and tm_value in service_mode_map:
            service_mode = service_mode_map[tm_value]
        # brand_map currently unused for Train.service_mode (would feed PDT/service_brand,
        # which is not modelled in the MERITS Train CSV). Kept in signature for callers.
        _ = brand_map

        # Operating dates — from DatedServiceJourney (required)
        dates = sj_dates.get(sj_id, [])
        if not dates:
            # All dates cancelled/replaced, or no DSJ at all — skip this journey
            continue

        first_day = dates[0].isoformat()
        last_day = dates[-1].isoformat()
        op_days = _operation_days_bitmask(dates, dates[0], dates[-1])

        emitted, journey_skipped = _resolve_journey_stops(sj, tt, quay_index)
        skipped_stops += journey_skipped

        total_stops = len(emitted)
        # MERITS requires a minimum of two stops per train (PRD/4_POP/POR).
        # Skip journeys that collapse to <2 UIC-resolvable stops; the
        # accompanying ODIs are also suppressed because no Train is emitted.
        if total_stops < 2:
            mode_key = tm_value or "(none)"
            skipped_by_mode[mode_key] = skipped_by_mode.get(mode_key, 0) + 1
            if tm_value == "rail":
                skipped_trains += 1
                skipped_rail_details.append(
                    (sj_id, train_number, total_stops + journey_skipped, total_stops)
                )
            continue

        train_id += 1
        conv_mode_key = tm_value or "(none)"
        converted_by_mode[conv_mode_key] = converted_by_mode.get(conv_mode_key, 0) + 1
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
        if train_sjs_out is not None:
            train_sjs_out.append(sj)

        if spijp_remap_out is not None:
            spijp_remap_out[train_id] = {
                ref: i for i, (ref, _, _, _) in enumerate(emitted, start=1)
            }

        journey_pors, por_id, journey_restricted = _build_pors_for_train(
            emitted, train_id, por_id, tt
        )
        pors.extend(journey_pors)
        restricted_stops += journey_restricted

    _log_conversion_summary(
        trains, pors,
        skipped_stops=skipped_stops,
        restricted_stops=restricted_stops,
        skipped_trains=skipped_trains,
        converted_by_mode=converted_by_mode,
        skipped_by_mode=skipped_by_mode,
        skipped_rail_details=skipped_rail_details,
    )

    # Update Meta validity period from actual train date ranges
    if trains:
        first_dates = [t.first_day for t in trains if t.first_day]
        last_dates = [t.last_day for t in trains if t.last_day]
        if first_dates and last_dates:
            meta_list[0].validity_first_date = min(first_dates)
            meta_list[0].validity_last_date = max(last_dates)

    return meta_list, trains, pors


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
    service_mode_map = load_mapping(cfg_dir / "mapping_service_mode.txt")
    if brand_map:
        logger.info("  Loaded brand map: %d entries", len(brand_map))
    if service_mode_map:
        logger.info("  Loaded service-mode map: %d entries", len(service_mode_map))

    logger.info("Loading station index from %s ...", station_zip.name)
    quay_index = _build_station_index(station_zip)
    logger.info("  %d quays indexed", len(quay_index))

    logger.info("Parsing timetable from %s ...", timetable_zip.name)
    tt = TimetableData(timetable_zip)
    logger.info("  %d SSP->Quay assignments", len(tt.ssp_to_quay))
    logger.info("  %d StopPointInJourneyPattern entries", len(tt.spijp_to_ssp))
    logger.info(
        "  %d DatedServiceJourney entries",
        sum(len(v) for v in tt.dated_journeys_by_sj().values()),
    )

    # Resolve originator: CLI override > ParticipantRef in NeTEx file
    participant = participant_ref(tt.shared_root) if tt.shared_root is not None else ""
    resolved_originator = resolve_originator(participant, originator)
    logger.info("  Originator: %r (ParticipantRef=%r)", resolved_originator, participant)

    meta_list, trains, pors = build_trains_and_pors(
        tt, quay_index, resolved_originator,
        brand_map=brand_map,
        service_mode_map=service_mode_map,
    )

    converter = CsvsToEdifact()
    converter.load({
        definition.META_FILE_NAME:     _rows(meta_list, Meta),
        definition.TRAIN_FILE_NAME:    _rows(trains, Train),
        definition.POR_FILE_NAME:      _rows(pors, Por),
        definition.RELATION_FILE_NAME: _rows([], Relation),
        definition.ODI_FILE_NAME:      _rows([], Odi),
    })
    edifact_text = converter.get()

    output_file.parent.mkdir(parents=True, exist_ok=True)
    output_file.write_text(edifact_text, encoding="utf-8")
    logger.info("Written SKDUPD EDIFACT to %s", output_file)

    # Also produce a unix-timestamped .zip alongside the .r file (MERITS
    # submission convention).
    import time, zipfile
    zip_path = output_file.parent / f"SKDUPD_{int(time.time())}.zip"
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.write(output_file, arcname=output_file.name)
    logger.info("Written SKDUPD ZIP to %s", zip_path)


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
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    args = _build_arg_parser().parse_args()
    convert(
        timetable_zip=Path(args.timetable),
        station_zip=Path(args.stations),
        output_file=Path(args.output),
        originator=args.originator,
    )


if __name__ == "__main__":
    main()
