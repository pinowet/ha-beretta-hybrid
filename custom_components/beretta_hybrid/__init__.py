"""Beretta hybrid system (Hydro Unit M + Mynute X + Hi,Comfort T300).

Passive listener of the RS485 Modbus bus through a Waveshare RS485-to-Ethernet
gateway in transparent TCP server mode. Nothing is ever sent on the bus.
"""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_PORT, Platform
from homeassistant.core import HomeAssistant

from .hub import BerettaHub

PLATFORMS: list[Platform] = [Platform.BINARY_SENSOR, Platform.SENSOR]

type BerettaConfigEntry = ConfigEntry[BerettaHub]


async def async_setup_entry(hass: HomeAssistant, entry: BerettaConfigEntry) -> bool:
    """Set up the integration from a config entry."""
    hub = BerettaHub(hass, entry.entry_id, entry.data[CONF_HOST], entry.data[CONF_PORT])
    entry.runtime_data = hub
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    hub.start()
    entry.async_on_unload(entry.add_update_listener(_async_options_updated))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: BerettaConfigEntry) -> bool:
    """Unload a config entry."""
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        await entry.runtime_data.stop()
    return unloaded


async def _async_options_updated(hass: HomeAssistant, entry: BerettaConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)
