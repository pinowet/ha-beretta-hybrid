"""Base entity for the Beretta hybrid integration."""

from __future__ import annotations

import time
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity import Entity, EntityDescription

from .const import CONF_MIN_INTERVAL, DEFAULT_MIN_INTERVAL, DOMAIN, MANUFACTURER, signal_update
from .decoding import DEVICE_BOILER, DEVICE_PDC, DEVICE_SLAVE, DEVICE_T300, Point
from .hub import BerettaHub

_MODELS = {
    DEVICE_PDC: "Hydro Unit M",
    DEVICE_BOILER: "Mynute X",
    DEVICE_T300: "Hi,Comfort T300",
}


def device_info(entry: ConfigEntry, device: str) -> DeviceInfo:
    """Device info for one of the three physical devices."""
    return DeviceInfo(
        identifiers={(DOMAIN, f"{entry.entry_id}_{device}")},
        translation_key=device,
        manufacturer=MANUFACTURER,
        model=_MODELS[device],
    )


class BerettaEntity(Entity):
    """Entity fed by the bus listener, with optional rate limiting."""

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(
        self,
        hub: BerettaHub,
        entry: ConfigEntry,
        description: EntityDescription,
        point: Point,
    ) -> None:
        self.entity_description = description
        self._hub = hub
        self._entry = entry
        self._point = point
        self._slave = DEVICE_SLAVE[point.device]
        self._attr_unique_id = f"{entry.entry_id}_{description.key}"
        self._attr_device_info = device_info(entry, point.device)
        self._min_interval = (
            float(entry.options.get(CONF_MIN_INTERVAL, DEFAULT_MIN_INTERVAL))
            if point.throttle
            else 0.0
        )
        self._value: Any = None
        self._last_write = 0.0
        self._last_available: bool | None = None

    @property
    def available(self) -> bool:
        return self._hub.slave_available(self._slave)

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass, signal_update(self._entry.entry_id), self._handle_update
            )
        )
        self._handle_update(force=True)

    def _set_value(self, value: Any) -> None:
        """Store the decoded value in the platform-specific attribute."""
        raise NotImplementedError

    @callback
    def _handle_update(self, force: bool = False) -> None:
        value = self._point.value_fn(self._hub.state)
        now = time.monotonic()
        changed = value != self._value
        if (
            changed
            and not force
            and self._value is not None
            and value is not None
            and now - self._last_write < self._min_interval
        ):
            changed = False  # rate limited, flushed on a later update
        if changed:
            self._value = value
            self._set_value(value)
        available = self.available
        if changed or force or available != self._last_available:
            self._last_available = available
            self._last_write = now
            if self.hass is not None:
                self.async_write_ha_state()
