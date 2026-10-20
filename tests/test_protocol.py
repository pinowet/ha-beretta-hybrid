"""Tests of the pure parser and register map against real captures."""

from __future__ import annotations

import random

from custom_components.beretta_hybrid.decoding import decode_all
from custom_components.beretta_hybrid.protocol import FrameParser, crc16

from .conftest import load_stream


def _parse(name: str, seed: int = 0) -> FrameParser:
    stream = load_stream(name)
    rng = random.Random(seed)
    parser = FrameParser(clock=lambda: 1000.0)
    i = 0
    while i < len(stream):
        n = rng.randint(1, 60)
        parser.feed(stream[i : i + n])
        i += n
    return parser


def test_crc() -> None:
    # Request "read 3 holding registers from 0" of slave 1, captured on the bus
    frame = bytes.fromhex("01 03 00 00 00 03 05 cb")
    crc = crc16(frame[:-2])
    assert frame[-2:] == bytes([crc & 0xFF, crc >> 8])


def test_dhw_with_burner_on() -> None:
    parser = _parse("dhw_burner_on")
    st = parser.state
    assert st.bytes_discarded == 0
    assert st.unmatched_responses == 0
    v = decode_all(st)
    # T300 INFO page at 09:44: 56.4 / 50.7 / 52.7 / 51.5 °C, fan 2272 rpm
    assert 50 < v["boiler_flow_temp"] < 60
    assert v["boiler_flame"] is True
    assert v["boiler_dhw_active"] is True
    assert v["t300_dhw_request"] is True
    assert v["t300_heating_request"] is False
    assert v["boiler_fan_speed"] > 2000
    assert v["boiler_dhw_setpoint"] == 50.0
    assert v["boiler_pressure"] == 1.5
    assert v["boiler_outdoor_temp"] is None  # probe not connected (-40.0)
    assert v["pdc_power"] is False
    assert v["pdc_operating_state"] == "off"
    assert v["pdc_energy_consumed"] == 3121


def test_heat_pump_heating() -> None:
    parser = _parse("heatpump_heating", seed=7)
    st = parser.state
    assert st.bytes_discarded == 0
    v = decode_all(st)
    # T300 INFO pages at 10:05: flow 31, return 26, outdoor 14, 47 Hz, 1.40 m³/h, 8.37 kW
    assert v["pdc_power"] is True
    assert v["pdc_operating_state"] == "heating"
    assert v["pdc_mode_set"] == "heating"
    assert v["pdc_water_setpoint_zone1"] == 48
    assert v["pdc_water_flow_temp"] == 31
    assert v["pdc_water_return"] == 26
    assert v["pdc_outdoor_temp"] == 14
    assert 40 <= v["pdc_compressor_frequency"] <= 50
    assert 1.3 <= v["pdc_water_flow"] <= 1.5
    assert 7.5 <= v["pdc_thermal_power"] <= 9.0
    assert v["pdc_compressor_hours"] == 1737
    assert v["pdc_capacity"] == 8
    assert v["pdc_error"] is False
    assert v["t300_heating_request"] is True
    assert v["boiler_flame"] is False


def test_garbage_is_skipped() -> None:
    stream = load_stream("heatpump_heating")
    parser = FrameParser(clock=lambda: 0.0)
    parser.feed(b"\xff\x00\x13\x37\xaa" + stream[:500] + b"\x01\x02" + stream[500:])
    assert parser.state.frames > 90
    assert parser.state.get(1, "h", 105) == 31
