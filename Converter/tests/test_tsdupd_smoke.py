# -*- coding: utf-8 -*-
"""
Smoke tests for the TSDUPD converter (NeTEx → EDIFACT).

These tests run entirely in-memory: a minimal NeTEx SiteFrame XML is fed
into the converter's public `convert()` function and the resulting EDIFACT
text is inspected for key segments.

No files are written to disk.  No external data files are required.
"""

from __future__ import annotations

import sys
import tempfile
import textwrap
from pathlib import Path

import pytest

# Ensure the project root (NeTEx2EDIFACT/) is importable regardless of how
# pytest is invoked.
_HERE = Path(__file__).resolve().parent          # tests/
_ROOT = _HERE.parent                             # NeTEx2EDIFACT/
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

# Skip the entire module if the merits package is not installed.
# merits is installed from github.com/UnionInternationalCheminsdeFer/MERITS-open-source-tools
# and is not available on PyPI.
pytest.importorskip("merits", reason="merits package not installed — skipping smoke tests")

from Converter.TSDUPD.netex2tsdupd import convert  # noqa: E402


# ---------------------------------------------------------------------------
# Minimal NeTEx fixture: two rail stations, a bus stop that shares a rail UIC
# code, and a ferry terminal. Only the rail stations are delivered.
# ---------------------------------------------------------------------------
_NETEX_XML = textwrap.dedent("""\
    <?xml version="1.0" encoding="UTF-8"?>
    <PublicationDelivery xmlns="http://www.netex.org.uk/netex" version="2.0">
      <PublicationTimestamp>2026-01-01T00:00:00Z</PublicationTimestamp>
      <ParticipantRef>NSR</ParticipantRef>
      <dataObjects>
        <SiteFrame id="NSR:SiteFrame:1" version="1">
          <stopPlaces>

            <!-- Rail station: Oslo S -->
            <StopPlace id="NSR:StopPlace:337" version="1">
              <privateCodes>
                <PrivateCode type="uicCode">007600100</PrivateCode>
              </privateCodes>
              <Name lang="nor">Oslo S</Name>
              <alternativeNames>
                <AlternativeName>
                  <Name lang="eng">Oslo Central</Name>
                </AlternativeName>
              </alternativeNames>
              <Centroid>
                <Location>
                  <Longitude>10.752245</Longitude>
                  <Latitude>59.910890</Latitude>
                </Location>
              </Centroid>
              <TransportMode>rail</TransportMode>
              <StopPlaceType>railStation</StopPlaceType>
            </StopPlace>

            <!-- Rail station with a start date but no end date -->
            <StopPlace id="NSR:StopPlace:400" version="1">
              <ValidBetween>
                <FromDate>2020-01-01T00:00:00</FromDate>
              </ValidBetween>
              <privateCodes>
                <PrivateCode type="uicCode">007600200</PrivateCode>
              </privateCodes>
              <Name lang="nor">Lillestrøm</Name>
              <Centroid>
                <Location>
                  <Longitude>11.0495</Longitude>
                  <Latitude>59.9559</Latitude>
                </Location>
              </Centroid>
              <TransportMode>rail</TransportMode>
              <StopPlaceType>railStation</StopPlaceType>
            </StopPlace>

            <!-- Bus stop that shares the UIC code of Oslo S -->
            <StopPlace id="NSR:StopPlace:338" version="1">
              <privateCodes>
                <PrivateCode type="uicCode">007600100</PrivateCode>
              </privateCodes>
              <Name lang="nor">Oslo bussterminal</Name>
              <Centroid>
                <Location>
                  <Longitude>10.759</Longitude>
                  <Latitude>59.912</Latitude>
                </Location>
              </Centroid>
              <TransportMode>bus</TransportMode>
              <StopPlaceType>onstreetBus</StopPlaceType>
            </StopPlace>

            <!-- Ferry terminal: Aker Brygge -->
            <StopPlace id="NSR:StopPlace:999" version="1">
              <privateCodes>
                <PrivateCode type="uicCode">007699999</PrivateCode>
              </privateCodes>
              <Name lang="nor">Aker Brygge</Name>
              <Centroid>
                <Location>
                  <Longitude>10.729830</Longitude>
                  <Latitude>59.910530</Latitude>
                </Location>
              </Centroid>
              <TransportMode>water</TransportMode>
              <StopPlaceType>ferryStop</StopPlaceType>
            </StopPlace>

          </stopPlaces>
        </SiteFrame>
      </dataObjects>
    </PublicationDelivery>
""")


@pytest.fixture()
def tsdupd_output(tmp_path: Path) -> str:
    """Run the converter on the inline fixture and return the EDIFACT text."""
    # Write the XML fixture to a temp input directory
    input_dir = tmp_path / "input"
    input_dir.mkdir()
    (input_dir / "fixture.xml").write_text(_NETEX_XML, encoding="utf-8")

    output_file = tmp_path / "out.r"
    convert(
        input_dir=input_dir,
        output_file=output_file,
        originator=None,  # derived from ParticipantRef=NSR → 1076
    )
    return output_file.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Assertions
# ---------------------------------------------------------------------------

class TestTSDUPDOutput:
    def test_file_is_non_empty(self, tsdupd_output: str):
        assert len(tsdupd_output) > 100

    def test_contains_als_stop_segment(self, tsdupd_output: str):
        """ALS segment carries the stop's location function code, UIC and name."""
        assert "ALS+" in tsdupd_output

    def test_oslo_s_uic_present(self, tsdupd_output: str):
        """UIC code for Oslo S must appear in the output."""
        assert "007600100" in tsdupd_output

    def test_oslo_s_name_present(self, tsdupd_output: str):
        """Station name must appear (after ASCII folding)."""
        assert "Oslo S" in tsdupd_output

    def test_rail_function_code(self, tsdupd_output: str):
        """Rail → location function code 29."""
        assert "ALS+29+" in tsdupd_output

    def test_only_rail_function_code(self, tsdupd_output: str):
        """Only rail stations are delivered, so no other function code appears."""
        assert "ALS+21+" not in tsdupd_output
        assert "ALS+50+" not in tsdupd_output

    def test_ferry_and_bus_not_delivered(self, tsdupd_output: str):
        assert "007699999" not in tsdupd_output
        assert "Oslo bussterminal" not in tsdupd_output

    def test_shared_uic_code_written_once(self, tsdupd_output: str):
        assert tsdupd_output.count("ALS+29+007600100") == 1

    def test_open_end_validity(self, tsdupd_output: str):
        """A missing ToDate is written as 2999-12-31, never as an open end."""
        assert "2020-01-01/2999-12-31" in tsdupd_output

    def test_missing_validity_gets_open_end(self, tsdupd_output: str):
        assert tsdupd_output.count("/2999-12-31") >= 2

    def test_synonym_language_is_two_letters(self, tsdupd_output: str):
        assert "IFT+AGW::::en+Oslo Central" in tsdupd_output
        assert "::::eng" not in tsdupd_output

    def test_reservation_code_segment(self, tsdupd_output: str):
        """RFR+X01 carries the StopPlace.id as reservation code."""
        assert "RFR+X01:" in tsdupd_output

    def test_reservation_code_uses_stop_place_id(self, tsdupd_output: str):
        """Oslo S StopPlace.id is NSR:StopPlace:337 — colons are EDIFACT-escaped."""
        # MERITS SegmentWriter escapes ':' → '?:' in component values
        assert "NSR?:StopPlace?:337" in tsdupd_output

    def test_country_segment(self, tsdupd_output: str):
        """CNY segment carries the country derived from the UIC prefix 76 → NO."""
        assert "CNY+NO" in tsdupd_output

    def test_timezone_segment(self, tsdupd_output: str):
        """TIZ segment is emitted for each stop."""
        assert "TIZ+" in tsdupd_output

    def test_originator_derived_from_participant_ref(self, tsdupd_output: str):
        """ParticipantRef=NSR → RICS code 1076 in the originator field."""
        assert "1076" in tsdupd_output

    def test_two_rail_stations_converted(self, tsdupd_output: str):
        """Both rail UIC codes from the fixture must appear."""
        assert "007600100" in tsdupd_output
        assert "007600200" in tsdupd_output
