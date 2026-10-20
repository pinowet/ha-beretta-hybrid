"""Diagnostics: full register table as seen on the bus."""

from __future__ import annotations

from typing import Any

from homeassistant.core import HomeAssistant

from . import BerettaConfigEntry
from .decoding import decode_all
from .protocol import s16


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: BerettaConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    hub = entry.runtime_data
    st = hub.state
    return {
        "connection": {
            "host": hub.host,
            "port": hub.port,
            "tcp_connected": hub.connected,
            "connections": hub.connections,
            "bus_alive": hub.bus_alive,
        },
        "counters": {
            "frames": st.frames,
            "bytes_received": st.bytes_received,
            "bytes_discarded": st.bytes_discarded,
            "unmatched_responses": st.unmatched_responses,
            "exceptions": st.exceptions,
            "last_frame": st.last_frame,
            "last_seen": {str(k): v for k, v in st.last_seen.items()},
        },
        "decoded": {k: str(v) for k, v in decode_all(st).items()},
        "registers": [
            {
                "slave": slave,
                "table": table,
                "register": reg,
                "u16": value,
                "s16": s16(value),
                "ts": ts,
            }
            for (slave, table, reg), (value, ts) in sorted(st.registers.items())
        ],
    }
