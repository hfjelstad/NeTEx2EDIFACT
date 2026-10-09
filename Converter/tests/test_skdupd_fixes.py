# -*- coding: utf-8 -*-
"""Unit tests for the SKDUPD fixes from the MERITS gap analysis."""

from __future__ import annotations

import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

pytest.importorskip("merits", reason="merits package not installed")

from Converter.Shared.edifact_mappings import to_iso639_1  # noqa: E402
from Converter.SKDUPD.netex2skdupd import (  # noqa: E402
    DEFAULT_CONFIG_DIR,
    _traffic_restriction_code,
    load_mapping,
)
from Converter.SKDUPD.run_conversion import _journeypart_stop_range  # noqa: E402

NS = "http://www.netex.org.uk/netex"


class TestTrafficRestriction:
    def test_normal_stop(self):
        assert _traffic_restriction_code(True, True) is None

    def test_boarding_only(self):
        assert _traffic_restriction_code(True, False) == "1"

    def test_alighting_only(self):
        assert _traffic_restriction_code(False, True) == "2"

    def test_technical_stop(self):
        assert _traffic_restriction_code(False, False, "noBoardingOrAlighting") == "3"

    def test_passthrough(self):
        assert _traffic_restriction_code(False, False, "passthrough") == "4"

    def test_neither_without_stop_use_stays_passage(self):
        assert _traffic_restriction_code(False, False) == "4"


class TestJourneyPartRange:
    # Stops 1..4 on one train; the first stop of the train is ssp A.
    _SPIJP_ORDER = {"sp1": 1, "sp2": 2, "sp3": 3, "sp4": 4}
    _SPIJP_TO_SSP = {"sp1": "A", "sp2": "B", "sp3": "C", "sp4": "D"}

    @staticmethod
    def _jp(xml_body: str) -> ET.Element:
        return ET.fromstring(f'<JourneyPart xmlns="{NS}">{xml_body}</JourneyPart>')

    def test_stop_point_refs_give_the_section(self):
        jp = self._jp('<FromStopPointRef ref="A"/><ToStopPointRef ref="C"/>')
        assert _journeypart_stop_range(
            jp, self._SPIJP_ORDER, [1, 2, 3, 4], self._SPIJP_TO_SSP
        ) == ("1", "3")

    def test_no_refs_gives_whole_route(self):
        jp = self._jp("")
        assert _journeypart_stop_range(
            jp, self._SPIJP_ORDER, [1, 2, 3, 4], self._SPIJP_TO_SSP
        ) == ("1", "4")

    def test_unknown_stop_point_falls_back_to_route_ends(self):
        jp = self._jp('<FromStopPointRef ref="X"/><ToStopPointRef ref="Y"/>')
        assert _journeypart_stop_range(
            jp, self._SPIJP_ORDER, [1, 2, 3, 4], self._SPIJP_TO_SSP
        ) == ("1", "4")

    def test_station_called_twice_takes_the_to_stop_after_from(self):
        order = {"sp1": 1, "sp2": 2, "sp3": 3, "sp4": 4}
        ssp = {"sp1": "A", "sp2": "B", "sp3": "C", "sp4": "B"}
        jp = self._jp('<FromStopPointRef ref="C"/><ToStopPointRef ref="B"/>')
        assert _journeypart_stop_range(jp, order, [1, 2, 3, 4], ssp) == ("3", "4")


class TestConfiguration:
    def test_local_trains_have_a_brand(self):
        assert load_mapping(DEFAULT_CONFIG_DIR / "mapping_brand.txt").get("local")

    def test_ferry_has_service_mode_33(self):
        assert load_mapping(DEFAULT_CONFIG_DIR / "mapping_service_mode.txt")["water"] == "33"


class TestLanguageCodes:
    @pytest.mark.parametrize("raw,expected", [
        ("eng", "en"), ("nor", "no"), ("fra", "fr"), ("no", "no"), ("EN", "en"),
        ("", ""), ("xyz", ""),
    ])
    def test_to_iso639_1(self, raw, expected):
        assert to_iso639_1(raw) == expected
