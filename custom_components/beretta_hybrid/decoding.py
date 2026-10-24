"""Register map of the Beretta hybrid system (PdC Hydro Unit M + Mynute X + T300).

Pure Python, no Home Assistant imports. Every value is derived from what the
T300 reads from, or writes to, the two slaves on the bus.

Slave 1   = heat pump Hydro Unit M (Midea M-Thermal holding register map)
Slave 100 = boiler Mynute X (input registers 1000..1017, commands 2000..2019,
            parameter block 3000..3079 written on every settings change)
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from .protocol import TABLE_HOLDING, TABLE_INPUT, TABLE_WRITTEN, BusState, s16

SLAVE_PDC = 1
SLAVE_BOILER = 100

DEVICE_PDC = "pdc"
DEVICE_BOILER = "boiler"
DEVICE_T300 = "t300"

DEVICE_SLAVE = {DEVICE_PDC: SLAVE_PDC, DEVICE_BOILER: SLAVE_BOILER, DEVICE_T300: SLAVE_BOILER}

PDC_MODE_SET = {1: "auto", 2: "cooling", 3: "heating"}
PDC_OPERATING_STATE = {0: "off", 2: "cooling", 3: "heating", 5: "dhw"}

BOILER_OUTDOOR_NOT_CONNECTED = -400


def _h(slave: int, reg: int) -> Callable[[BusState], int | None]:
    return lambda st: st.get(slave, TABLE_HOLDING, reg)


def _pdc_signed(reg: int) -> Callable[[BusState], int | None]:
    def fn(st: BusState) -> int | None:
        raw = st.get(SLAVE_PDC, TABLE_HOLDING, reg)
        return None if raw is None else s16(raw)

    return fn


def _pdc_scaled(reg: int, scale: float, digits: int) -> Callable[[BusState], float | None]:
    def fn(st: BusState) -> float | None:
        raw = st.get(SLAVE_PDC, TABLE_HOLDING, reg)
        return None if raw is None else round(raw * scale, digits)

    return fn


def _boiler_tenths(reg: int) -> Callable[[BusState], float | None]:
    def fn(st: BusState) -> float | None:
        raw = st.get(SLAVE_BOILER, TABLE_INPUT, reg)
        return None if raw is None else round(s16(raw) / 10, 1)

    return fn


def _boiler_raw(reg: int) -> Callable[[BusState], int | None]:
    return lambda st: st.get(SLAVE_BOILER, TABLE_INPUT, reg)


def _bit(slave: int, table: str, reg: int, mask: int) -> Callable[[BusState], bool | None]:
    def fn(st: BusState) -> bool | None:
        raw = st.get(slave, table, reg)
        return None if raw is None else bool(raw & mask)

    return fn


def _enum(reg: int, mapping: dict[int, str]) -> Callable[[BusState], str | None]:
    def fn(st: BusState) -> str | None:
        raw = st.get(SLAVE_PDC, TABLE_HOLDING, reg)
        return None if raw is None else mapping.get(raw)

    return fn


def _setpoint_zone(shift: int) -> Callable[[BusState], int | None]:
    def fn(st: BusState) -> int | None:
        raw = st.get(SLAVE_PDC, TABLE_HOLDING, 2)
        return None if raw is None else (raw >> shift) & 0xFF

    return fn


def _pdc_energy(st: BusState) -> int | None:
    high = st.get(SLAVE_PDC, TABLE_HOLDING, 143)
    low = st.get(SLAVE_PDC, TABLE_HOLDING, 144)
    if high is None or low is None:
        return None
    return (high << 16) | low


def _pdc_positive(reg: int) -> Callable[[BusState], bool | None]:
    def fn(st: BusState) -> bool | None:
        raw = st.get(SLAVE_PDC, TABLE_HOLDING, reg)
        return None if raw is None else raw > 0

    return fn


def _boiler_outdoor(st: BusState) -> float | None:
    raw = st.get(SLAVE_BOILER, TABLE_INPUT, 1010)
    if raw is None or s16(raw) == BOILER_OUTDOOR_NOT_CONNECTED:
        return None
    return round(s16(raw) / 10, 1)


def _dhw_setpoint(st: BusState) -> float | None:
    raw = st.get(SLAVE_BOILER, TABLE_WRITTEN, 2002)
    return None if raw is None else round(raw / 10, 1)


def _params_update(st: BusState) -> float | None:
    return st.block_writes.get((SLAVE_BOILER, TABLE_WRITTEN, 3000))


@dataclass(frozen=True)
class Point:
    """A value decoded from the bus."""

    key: str
    device: str
    value_fn: Callable[[BusState], Any]
    # High-frequency values are rate limited before being written to HA
    throttle: bool = False


SENSOR_POINTS: tuple[Point, ...] = (
    # ---------------------------------------------------------------- PdC
    Point("pdc_mode_set", DEVICE_PDC, _enum(1, PDC_MODE_SET)),
    Point("pdc_operating_state", DEVICE_PDC, _enum(101, PDC_OPERATING_STATE)),
    Point("pdc_water_setpoint_zone1", DEVICE_PDC, _setpoint_zone(0)),
    Point("pdc_water_setpoint_zone2", DEVICE_PDC, _setpoint_zone(8)),
    Point("pdc_compressor_frequency", DEVICE_PDC, _h(SLAVE_PDC, 100), throttle=True),
    Point("pdc_water_return", DEVICE_PDC, _pdc_signed(104)),
    Point("pdc_water_flow_temp", DEVICE_PDC, _pdc_signed(105)),
    Point("pdc_outdoor_temp", DEVICE_PDC, _pdc_signed(107)),
    Point("pdc_discharge_temp", DEVICE_PDC, _pdc_signed(108)),
    Point("pdc_suction_temp", DEVICE_PDC, _pdc_signed(109)),
    Point("pdc_exchanger_refrigerant_temp", DEVICE_PDC, _pdc_signed(112)),
    Point("pdc_condenser_refrigerant_temp", DEVICE_PDC, _pdc_signed(113)),
    Point("pdc_compressor_hours", DEVICE_PDC, _h(SLAVE_PDC, 122)),
    Point("pdc_capacity", DEVICE_PDC, _h(SLAVE_PDC, 123)),
    Point("pdc_error_code", DEVICE_PDC, _h(SLAVE_PDC, 124)),
    Point("pdc_status_128", DEVICE_PDC, _h(SLAVE_PDC, 128)),
    Point("pdc_status_129", DEVICE_PDC, _h(SLAVE_PDC, 129)),
    Point("pdc_water_flow", DEVICE_PDC, _pdc_scaled(138, 0.01, 2), throttle=True),
    Point("pdc_thermal_power", DEVICE_PDC, _pdc_scaled(140, 0.01, 2), throttle=True),
    Point("pdc_energy_consumed", DEVICE_PDC, _pdc_energy),
    # ------------------------------------------------------------- Caldaia
    Point("boiler_pressure", DEVICE_BOILER, lambda st: _scaled_input(st, 1003, 0.1, 1)),
    Point("boiler_flow_temp", DEVICE_BOILER, _boiler_tenths(1006), throttle=True),
    Point("boiler_return_temp", DEVICE_BOILER, _boiler_tenths(1007), throttle=True),
    Point("boiler_dhw_temp", DEVICE_BOILER, _boiler_tenths(1008), throttle=True),
    Point("boiler_flue_temp", DEVICE_BOILER, _boiler_tenths(1009), throttle=True),
    Point("boiler_outdoor_temp", DEVICE_BOILER, _boiler_outdoor, throttle=True),
    Point("boiler_fan_speed", DEVICE_BOILER, _boiler_raw(1013), throttle=True),
    Point("boiler_fan_target", DEVICE_BOILER, _boiler_raw(1012), throttle=True),
    Point("boiler_status", DEVICE_BOILER, _boiler_raw(1014)),
    Point("boiler_dhw_setpoint", DEVICE_BOILER, _dhw_setpoint),
    # ----------------------------------------------------------------- T300
    Point("t300_command_word", DEVICE_T300, lambda st: st.get(SLAVE_BOILER, TABLE_WRITTEN, 2000)),
    Point("t300_params_update", DEVICE_T300, _params_update),
)

# Register 128 of the heat pump ("status bit 1" of the Midea M-Thermal map).
# 0x0400 is always set on this hybrid unit (boiler configured as auxiliary
# heat source); 0x2000 is defrosting according to the Midea-clone map.
# TODO: confirm the defrost bit on a real defrost cycle.
PDC_STATUS_AUX_HEAT_SOURCE = 0x0400
PDC_STATUS_DEFROST = 0x2000
PDC_STATUS_ANTIFREEZE = 0x4000
PDC_STATUS_OIL_RETURN = 0x8000

BINARY_POINTS: tuple[Point, ...] = (
    Point("pdc_power", DEVICE_PDC, lambda st: _ne_zero(st.get(SLAVE_PDC, TABLE_HOLDING, 0))),
    Point("pdc_compressor_running", DEVICE_PDC, _pdc_positive(100)),
    Point("pdc_circulation", DEVICE_PDC, _pdc_positive(138)),
    Point("pdc_error", DEVICE_PDC, _pdc_positive(124)),
    Point("pdc_defrost", DEVICE_PDC, _bit(SLAVE_PDC, TABLE_HOLDING, 128, PDC_STATUS_DEFROST)),
    Point(
        "pdc_antifreeze", DEVICE_PDC, _bit(SLAVE_PDC, TABLE_HOLDING, 128, PDC_STATUS_ANTIFREEZE)
    ),
    Point(
        "pdc_oil_return", DEVICE_PDC, _bit(SLAVE_PDC, TABLE_HOLDING, 128, PDC_STATUS_OIL_RETURN)
    ),
    Point(
        "pdc_aux_heat_source",
        DEVICE_PDC,
        _bit(SLAVE_PDC, TABLE_HOLDING, 128, PDC_STATUS_AUX_HEAT_SOURCE),
    ),
    Point("boiler_flame", DEVICE_BOILER, _bit(SLAVE_BOILER, TABLE_INPUT, 1014, 0x0008)),
    Point("boiler_dhw_active", DEVICE_BOILER, _bit(SLAVE_BOILER, TABLE_INPUT, 1014, 0x0002)),
    Point("t300_heating_request", DEVICE_T300, _bit(SLAVE_BOILER, TABLE_WRITTEN, 2000, 0x0400)),
    Point("t300_dhw_request", DEVICE_T300, _bit(SLAVE_BOILER, TABLE_WRITTEN, 2000, 0x0004)),
)


def _scaled_input(st: BusState, reg: int, scale: float, digits: int) -> float | None:
    raw = st.get(SLAVE_BOILER, TABLE_INPUT, reg)
    return None if raw is None else round(raw * scale, digits)


def _ne_zero(value: int | None) -> bool | None:
    return None if value is None else value != 0


def decode_all(st: BusState) -> dict[str, Any]:
    """Decode every point (used by tests and diagnostics)."""
    return {p.key: p.value_fn(st) for p in (*SENSOR_POINTS, *BINARY_POINTS)}
