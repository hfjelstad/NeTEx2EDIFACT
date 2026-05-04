# -*- coding: utf-8 -*-
"""
netex_helpers.py
~~~~~~~~~~~~~~~~
Shared, pure-NeTEx parsing primitives used by every converter in this folder
(:mod:`netex2tsdupd`, :mod:`netex2tsdupd_csv`, :mod:`netex2skdupd`).

This module deliberately knows NOTHING about EDIFACT, MERITS, or any output
format. It only walks NeTEx elements and returns plain Python types. Keeping
the layer thin and side-effect free is what lets the same logic be reused
across SKDUPD (timetable), TSDUPD (stop) and any future converter.

For EDIFACT-specific lookup tables (RICS codes, country/timezone tables,
ASCII folding) see :mod:`edifact_mappings`.
"""

from __future__ import annotations

from dataclasses import asdict, fields
from typing import Iterable, List, Type, TypeVar

NS = "http://www.netex.org.uk/netex"
T = TypeVar("T")


# ---------------------------------------------------------------------------
# Element / attribute readers
# ---------------------------------------------------------------------------

def text(element, tag: str) -> str:
    """Return stripped text of first matching child ``<{NS}tag>``, or ''."""
    el = element.find(f"{{{NS}}}{tag}")
    return el.text.strip() if el is not None and el.text else ""


def ref(element, tag: str) -> str:
    """Return the ``ref`` attribute of the first matching child, or ''."""
    el = element.find(f"{{{NS}}}{tag}")
    return el.get("ref", "") if el is not None else ""


def attr(element, tag: str, attribute: str) -> str:
    """Return an attribute value of the first matching child tag, or ''."""
    el = element.find(f"{{{NS}}}{tag}")
    return el.get(attribute, "") if el is not None else ""


# ---------------------------------------------------------------------------
# privateCodes / PrivateCode helpers
# ---------------------------------------------------------------------------

def private_code(element, type_attr: str) -> str:
    """Return ``<privateCodes>/<PrivateCode type=type_attr>`` text, or ''.

    Match is case-insensitive on the ``type`` attribute since profiles vary
    between camelCase and lowercase (e.g. ``uicCode`` vs ``uiccode``).
    """
    target = type_attr.lower()
    for pc in element.findall(f"{{{NS}}}privateCodes/{{{NS}}}PrivateCode"):
        if pc.get("type", "").lower() == target:
            return (pc.text or "").strip()
    return ""


def uic_code(stop_place, accept_legacy: bool = True) -> str:
    """Return UIC code for a StopPlace.

    Prefers the typed NeTEx 2.0 form
    ``privateCodes/PrivateCode[@type='uicCode']``. If ``accept_legacy`` is
    true (default) and that lookup fails, falls back to the legacy singleton
    direct child ``<PrivateCode>NNN</PrivateCode>`` used by older NSR exports.
    """
    code = private_code(stop_place, "uicCode")
    if code:
        return code
    if accept_legacy:
        pc = stop_place.find(f"{{{NS}}}PrivateCode")
        if pc is not None and pc.text:
            return pc.text.strip()
    return ""


def reservation_code(stop_place) -> str:
    """Return reservation code if present in privateCodes, else ''."""
    return private_code(stop_place, "reservationCode")


# ---------------------------------------------------------------------------
# Geographic + temporal scalars
# ---------------------------------------------------------------------------

def coordinates(stop_place):
    """Return ``(latitude, longitude)`` strings, or ('', '')."""
    lon_el = stop_place.find(
        f".//{{{NS}}}Centroid/{{{NS}}}Location/{{{NS}}}Longitude"
    )
    lat_el = stop_place.find(
        f".//{{{NS}}}Centroid/{{{NS}}}Location/{{{NS}}}Latitude"
    )
    lon = lon_el.text.strip() if lon_el is not None and lon_el.text else ""
    lat = lat_el.text.strip() if lat_el is not None and lat_el.text else ""
    return lat, lon


def validity(stop_place):
    """Return ``(valid_from, valid_to)`` as ``YYYY-MM-DD`` or ('', '')."""
    vb = stop_place.find(f"{{{NS}}}ValidBetween")
    if vb is None:
        return "", ""
    from_el = vb.find(f"{{{NS}}}FromDate")
    to_el = vb.find(f"{{{NS}}}ToDate")
    return (
        from_el.text[:10] if from_el is not None and from_el.text else "",
        to_el.text[:10] if to_el is not None and to_el.text else "",
    )


def alt_names(stop_place):
    """Yield ``(language, name)`` for each ``<AlternativeName>`` child."""
    for an in stop_place.findall(f".//{{{NS}}}AlternativeName"):
        name_el = an.find(f"{{{NS}}}Name")
        lang = name_el.get("lang", "") if name_el is not None else ""
        name = name_el.text.strip() if name_el is not None and name_el.text else ""
        if name:
            yield lang, name


# ---------------------------------------------------------------------------
# Durations and SiteConnection (MCT) extraction
# ---------------------------------------------------------------------------

def iso_duration_to_minutes(duration: str) -> int:
    """Convert ISO 8601 duration like ``PT8M`` / ``PT1H30M`` to integer minutes.

    Returns 0 for unparseable / empty input. Only hours and minutes of the
    time component are considered — day/year fields are ignored because
    transfer / dwell durations are always sub-day.
    """
    if not duration or not duration.startswith("PT"):
        return 0
    rest = duration[2:]
    minutes = 0
    num = ""
    for ch in rest:
        if ch.isdigit():
            num += ch
        elif ch == "H" and num:
            minutes += int(num) * 60
            num = ""
        elif ch == "M" and num:
            minutes += int(num)
            num = ""
        else:
            num = ""
    return minutes


def build_uic_to_mct(root) -> dict:
    """Build ``{uic_code: minutes}`` from SiteConnection self-loops.

    A SiteConnection is treated as a per-station Minimum Connection Time
    (MCT) when both ``From/StopPlaceRef`` and ``To/StopPlaceRef`` resolve to
    the same StopPlace. Operator/brand-scoped SiteConnections are skipped
    here — they belong in a per-pair MCT table, not in the per-stop default.
    """
    sp_id_to_uic: dict = {}
    for sp in root.findall(f".//{{{NS}}}StopPlace"):
        sp_id = sp.get("id")
        code = uic_code(sp)
        if sp_id and code:
            sp_id_to_uic[sp_id] = code

    out: dict = {}
    for sc in root.findall(f".//{{{NS}}}SiteConnection"):
        from_ref = sc.find(f"{{{NS}}}From/{{{NS}}}StopPlaceRef")
        to_ref = sc.find(f"{{{NS}}}To/{{{NS}}}StopPlaceRef")
        if from_ref is None or to_ref is None:
            continue
        if from_ref.get("ref") != to_ref.get("ref"):
            continue  # not a self-loop
        code = sp_id_to_uic.get(from_ref.get("ref"))
        if not code:
            continue
        dd = sc.find(f".//{{{NS}}}TransferDuration/{{{NS}}}DefaultDuration")
        if dd is None or not (dd.text or "").strip():
            continue
        minutes = iso_duration_to_minutes(dd.text.strip())
        if minutes > 0:
            out[code] = minutes
    return out


# ---------------------------------------------------------------------------
# PublicationDelivery participant
# ---------------------------------------------------------------------------

def participant_ref(root) -> str:
    """Return ``<ParticipantRef>`` text, or the codespace prefix of a frame id.

    Falls back to the leading segment (before ``:``) of any element id when
    no explicit ParticipantRef is present. Returns '' if neither is found.
    """
    el = root.find(f"{{{NS}}}ParticipantRef")
    if el is not None and el.text:
        return el.text.strip()
    for child in root.iter():
        cid = child.get("id", "")
        if ":" in cid:
            return cid.split(":", 1)[0]
    return ""


# ---------------------------------------------------------------------------
# MERITS RowsInMemory adapter
# ---------------------------------------------------------------------------

def rows_in_memory(instances: List[T], cls: Type[T]):
    """Wrap a list of dataclass instances as MERITS ``RowsInMemory``.

    Imported lazily so this module stays usable in contexts where the MERITS
    package is not installed (e.g. simple validation scripts).
    """
    from merits.csvs_zip.rows import RowsInMemory  # local import

    headers = [f.name for f in fields(cls)]
    data = [
        {k: ("" if v is None else str(v)) for k, v in asdict(obj).items()}
        for obj in instances
    ]
    return RowsInMemory(data=data, headers=headers)
