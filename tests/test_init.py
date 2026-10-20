"""End-to-end tests inside Home Assistant with a fake gateway."""

from __future__ import annotations

import asyncio
from unittest.mock import patch

from homeassistant import config_entries
from homeassistant.const import CONF_HOST, CONF_PORT, STATE_OFF, STATE_ON
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.beretta_hybrid.const import CONF_MIN_INTERVAL, DOMAIN


async def _setup(hass: HomeAssistant, port: int) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_HOST: "127.0.0.1", CONF_PORT: port},
        unique_id=f"127.0.0.1:{port}",
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


def _state(hass: HomeAssistant, entry: MockConfigEntry, domain: str, key: str):
    entity_id = er.async_get(hass).async_get_entity_id(domain, DOMAIN, f"{entry.entry_id}_{key}")
    assert entity_id, key
    return hass.states.get(entity_id)


async def _wait(hass: HomeAssistant, predicate, timeout: float = 8.0) -> None:
    for _ in range(int(timeout / 0.1)):
        await asyncio.sleep(0.1)
        await hass.async_block_till_done()
        if predicate():
            return
    raise AssertionError("condition not reached")


async def test_heat_pump_entities_and_receive_only(
    hass: HomeAssistant, socket_enabled, gateway_factory
) -> None:
    gw = await gateway_factory("heatpump_heating")
    entry = await _setup(hass, gw.port)

    await _wait(hass, lambda: _state(hass, entry, "sensor", "pdc_water_flow_temp").state == "31")

    assert _state(hass, entry, "sensor", "pdc_water_return").state == "26"
    assert _state(hass, entry, "sensor", "pdc_outdoor_temp").state == "14"
    assert _state(hass, entry, "sensor", "pdc_operating_state").state == "heating"
    assert _state(hass, entry, "sensor", "pdc_water_setpoint_zone1").state == "48"
    assert float(_state(hass, entry, "sensor", "pdc_thermal_power").state) > 7
    assert _state(hass, entry, "sensor", "pdc_energy_consumed").state == "3121"
    assert _state(hass, entry, "binary_sensor", "pdc_power").state == STATE_ON
    assert _state(hass, entry, "binary_sensor", "pdc_compressor_running").state == STATE_ON
    assert _state(hass, entry, "binary_sensor", "t300_heating_request").state == STATE_ON
    assert _state(hass, entry, "binary_sensor", "boiler_flame").state == STATE_OFF
    assert _state(hass, entry, "binary_sensor", "bus").state == STATE_ON

    # The integration must never transmit anything to the gateway
    assert gw.clients == 1
    assert bytes(gw.received) == b""

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()


async def test_dhw_burner(hass: HomeAssistant, socket_enabled, gateway_factory) -> None:
    gw = await gateway_factory("dhw_burner_on")
    entry = await _setup(hass, gw.port)
    await _wait(
        hass, lambda: _state(hass, entry, "binary_sensor", "boiler_flame").state == STATE_ON
    )
    assert _state(hass, entry, "binary_sensor", "boiler_dhw_active").state == STATE_ON
    assert _state(hass, entry, "sensor", "boiler_dhw_setpoint").state == "50.0"
    assert _state(hass, entry, "sensor", "boiler_pressure").state == "1.5"
    assert float(_state(hass, entry, "sensor", "boiler_flow_temp").state) > 50
    # Outdoor probe of the boiler is not connected: disabled by default
    entity_id = er.async_get(hass).async_get_entity_id(
        "sensor", DOMAIN, f"{entry.entry_id}_boiler_outdoor_temp"
    )
    assert er.async_get(hass).async_get(entity_id).disabled
    assert bytes(gw.received) == b""
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_unavailable_without_gateway(hass: HomeAssistant, socket_enabled) -> None:
    entry = await _setup(hass, 1)  # nothing listening
    state = _state(hass, entry, "sensor", "pdc_water_flow_temp")
    assert state.state == "unavailable"
    assert _state(hass, entry, "binary_sensor", "bus").state == STATE_OFF
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_config_flow(hass: HomeAssistant) -> None:
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM

    with patch(
        "custom_components.beretta_hybrid.config_flow.async_test_connection",
        side_effect=OSError,
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_HOST: "192.168.0.70", CONF_PORT: 4196}
        )
    assert result["errors"] == {"base": "cannot_connect"}

    with (
        patch("custom_components.beretta_hybrid.config_flow.async_test_connection"),
        patch("custom_components.beretta_hybrid.async_setup_entry", return_value=True),
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_HOST: "192.168.0.70", CONF_PORT: 4196}
        )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"] == {CONF_HOST: "192.168.0.70", CONF_PORT: 4196}


async def test_options_flow(hass: HomeAssistant) -> None:
    entry = MockConfigEntry(domain=DOMAIN, data={CONF_HOST: "x", CONF_PORT: 1})
    entry.add_to_hass(hass)
    with patch("custom_components.beretta_hybrid.async_setup_entry", return_value=True):
        result = await hass.config_entries.options.async_init(entry.entry_id)
        assert result["type"] is FlowResultType.FORM
        result = await hass.config_entries.options.async_configure(
            result["flow_id"], {CONF_MIN_INTERVAL: 60}
        )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options == {CONF_MIN_INTERVAL: 60}
