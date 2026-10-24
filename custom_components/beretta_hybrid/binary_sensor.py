"""Binary sensors for the Beretta hybrid integration."""

from __future__ import annotations

from typing import Any

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import BerettaConfigEntry
from .const import signal_update
from .decoding import BINARY_POINTS, DEVICE_T300
from .entity import BerettaEntity, device_info
from .hub import BerettaHub

PARALLEL_UPDATES = 0

_DESCRIPTIONS: dict[str, dict[str, Any]] = {
    "pdc_power": {"device_class": BinarySensorDeviceClass.POWER},
    "pdc_compressor_running": {"device_class": BinarySensorDeviceClass.RUNNING},
    "pdc_circulation": {"device_class": BinarySensorDeviceClass.RUNNING},
    "pdc_error": {"device_class": BinarySensorDeviceClass.PROBLEM},
    "pdc_defrost": {"device_class": BinarySensorDeviceClass.RUNNING},
    "pdc_antifreeze": {
        "device_class": BinarySensorDeviceClass.RUNNING,
        "entity_category": EntityCategory.DIAGNOSTIC,
    },
    "pdc_oil_return": {
        "device_class": BinarySensorDeviceClass.RUNNING,
        "entity_category": EntityCategory.DIAGNOSTIC,
    },
    "pdc_aux_heat_source": {"entity_category": EntityCategory.DIAGNOSTIC},
    "boiler_flame": {"device_class": BinarySensorDeviceClass.HEAT},
    "boiler_dhw_active": {"device_class": BinarySensorDeviceClass.RUNNING},
    "t300_heating_request": {"device_class": BinarySensorDeviceClass.HEAT},
    "t300_dhw_request": {},
}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: BerettaConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up binary sensors."""
    hub = entry.runtime_data
    entities: list[BinarySensorEntity] = [
        BerettaBinarySensor(
            hub,
            entry,
            BinarySensorEntityDescription(
                key=point.key, translation_key=point.key, **_DESCRIPTIONS[point.key]
            ),
            point,
        )
        for point in BINARY_POINTS
    ]
    entities.append(BerettaBusSensor(hub, entry))
    async_add_entities(entities)


class BerettaBinarySensor(BerettaEntity, BinarySensorEntity):
    """A boolean value decoded from the Modbus bus."""

    def _set_value(self, value: Any) -> None:
        self._attr_is_on = value


class BerettaBusSensor(BinarySensorEntity):
    """Connectivity of the RS485 bus (valid frames received recently)."""

    _attr_has_entity_name = True
    _attr_should_poll = False
    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_translation_key = "bus"

    def __init__(self, hub: BerettaHub, entry: BerettaConfigEntry) -> None:
        self._hub = hub
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_bus"
        self._attr_device_info = device_info(entry, DEVICE_T300)

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass, signal_update(self._entry.entry_id), self._handle_update
            )
        )
        self._handle_update()

    @callback
    def _handle_update(self) -> None:
        is_on = self._hub.bus_alive
        if is_on != self._attr_is_on:
            self._attr_is_on = is_on
            self.async_write_ha_state()

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {"tcp_connected": self._hub.connected, "connections": self._hub.connections}
