# -*- coding: utf-8 -*-
"""
edifact_mappings.py
~~~~~~~~~~~~~~~~~~~
Shared lookup tables used by the NeTEx → EDIFACT converters
(:mod:`netex2tsdupd`, :mod:`netex2tsdupd_csv`, etc.).

Kept in a dedicated module to:
  * avoid duplication across converters,
  * keep the converter scripts focused on transformation logic, and
  * make extending the tables (new RICS codes, new countries) a single edit.
"""

from __future__ import annotations

import unicodedata

# ---------------------------------------------------------------------------
# NeTEx <ParticipantRef>  →  EDIFACT ORG/3036 (UIC/RICS company code)
# ---------------------------------------------------------------------------
PARTICIPANT_TO_RICS = {
    "NSR":   "1076",   # Bane NOR / Norwegian National Stop Register
    "ENTUR": "1176",   # Entur (national access point operator)
    "FLB":   "1076",   # Flåmsbana (Vy Group)
    "GJB":   "1076",   # Gjøvikbanen
    "GOA":   "3733",   # Go-Ahead Nordic
    "NSB":   "1185",   # NSB / Vy
    "SJN":   "3781",   # SJ Norge
    "VYG":   "1076",   # Vy Group
    "PE":    "5100",   # PKP / Polish railways (case studies)
}


# ---------------------------------------------------------------------------
# UIC country code (digits 2-3 of a 9-digit UIC station code) → ISO 3166-1 α-2
# Source: UIC leaflet 920-14. Extend as needed.
# ---------------------------------------------------------------------------
UIC_TO_ISO_COUNTRY = {
    "10": "FI", "20": "RU", "21": "BY", "22": "UA", "23": "MD",
    "24": "LT", "25": "LV", "26": "EE",
    "33": "AL", "41": "ME", "42": "MK", "44": "BA", "49": "BA",
    "50": "BA", "51": "PL", "52": "BG", "53": "RO", "54": "CZ",
    "55": "HU", "56": "SK", "57": "AZ", "58": "AM", "59": "GE",
    "60": "IE", "61": "KR", "62": "MN", "63": "VN", "65": "MK",
    "66": "KZ", "67": "SY", "68": "TJ",
    "70": "GB", "71": "ES", "72": "RS", "73": "GR", "74": "SE",
    "75": "TR", "76": "NO", "78": "HR", "79": "SI",
    "80": "DE", "81": "AT", "82": "LU", "83": "IT", "84": "NL",
    "85": "CH", "86": "DK", "87": "FR", "88": "BE",
    "91": "TN", "92": "DZ", "93": "MA", "94": "PT", "95": "IL",
    "96": "IR", "97": "TR", "98": "CY", "99": "IQ",
}


# ---------------------------------------------------------------------------
# ISO 3166-1 α-2 → (time_zone, time_variation_hours) for EDIFACT TIZ.
# Standard-time offset only; CNY/winter_variation and summer_variation
# carry DST information separately.
# ---------------------------------------------------------------------------
COUNTRY_TO_TIMEZONE = {
    "NO": ("CET", "1"), "SE": ("CET", "1"), "DK": ("CET", "1"), "DE": ("CET", "1"),
    "NL": ("CET", "1"), "BE": ("CET", "1"), "LU": ("CET", "1"), "FR": ("CET", "1"),
    "CH": ("CET", "1"), "AT": ("CET", "1"), "IT": ("CET", "1"), "ES": ("CET", "1"),
    "PL": ("CET", "1"), "CZ": ("CET", "1"), "SK": ("CET", "1"), "HU": ("CET", "1"),
    "SI": ("CET", "1"), "HR": ("CET", "1"), "BA": ("CET", "1"), "RS": ("CET", "1"),
    "ME": ("CET", "1"), "MK": ("CET", "1"), "AL": ("CET", "1"),
    "FI": ("EET", "2"), "EE": ("EET", "2"), "LV": ("EET", "2"), "LT": ("EET", "2"),
    "BG": ("EET", "2"), "RO": ("EET", "2"), "GR": ("EET", "2"), "UA": ("EET", "2"),
    "MD": ("EET", "2"), "BY": ("EET", "2"), "TR": ("EET", "3"),
    "GB": ("GMT", "0"), "IE": ("GMT", "0"), "PT": ("GMT", "0"), "IS": ("GMT", "0"),
    "RU": ("MSK", "3"),
}


# ---------------------------------------------------------------------------
# ASCII transliteration for Nordic / common European glyphs that
# unicodedata.NFKD does NOT decompose (ø, æ, ß, etc.).
# EDIFACT messages emitted with UIB charset UNOB:4 must stay within a
# restricted character set; UTF-8 input causes mojibake in downstream
# validators, so we transliterate up front.
# ---------------------------------------------------------------------------
_ASCII_FOLD = str.maketrans({
    "ø": "o", "Ø": "O",
    "æ": "ae", "Æ": "AE",
    "ß": "ss",
    "ł": "l", "Ł": "L",
    "đ": "d", "Đ": "D",
    "ð": "d", "Ð": "D",
    "þ": "th", "Þ": "Th",
})


# ---------------------------------------------------------------------------
# Helpers built on the tables above
# ---------------------------------------------------------------------------

def to_ascii(text: str) -> str:
    """Fold non-ASCII characters to a safe ASCII equivalent for EDIFACT."""
    if not text:
        return text
    folded = text.translate(_ASCII_FOLD)
    decomposed = unicodedata.normalize("NFKD", folded)
    return decomposed.encode("ascii", "ignore").decode("ascii")


def country_from_uic(uic: str) -> str:
    """ISO 3166-1 α-2 country code derived from a 9-digit UIC station code.

    The UIC country code lives in digits 2-3 of the 9-digit form
    (the leading two digits are a check/format prefix, typically '00').
    Returns '' if no mapping is known.
    """
    if len(uic) >= 4 and uic.startswith("00"):
        cc = uic[2:4]
    elif len(uic) >= 2:
        cc = uic[:2]
    else:
        return ""
    return UIC_TO_ISO_COUNTRY.get(cc, "")


def timezone_for_country(iso_country: str):
    """Return ``(zone, variation)`` tuple, or ``(None, None)`` if unknown."""
    return COUNTRY_TO_TIMEZONE.get(iso_country, (None, None))


def resolve_originator(participant: str, override: str | None) -> str:
    """Resolve the EDIFACT ORG/3036 originator for a NeTEx ParticipantRef.

    ``override`` (CLI ``--originator``) wins; otherwise looked up in
    :data:`PARTICIPANT_TO_RICS`. Raises :class:`SystemExit` with a clear
    instruction if the mapping is missing.
    """
    if override:
        return override
    if participant in PARTICIPANT_TO_RICS:
        return PARTICIPANT_TO_RICS[participant]
    raise SystemExit(
        f"Cannot resolve EDIFACT originator: ParticipantRef '{participant}' "
        f"is not in PARTICIPANT_TO_RICS. Pass --originator <RICS-code> "
        f"explicitly or extend the mapping in edifact_mappings.py."
    )
