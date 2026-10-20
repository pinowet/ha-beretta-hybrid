"""Constants for the Beretta hybrid integration."""

from __future__ import annotations

DOMAIN = "beretta_hybrid"

CONF_MIN_INTERVAL = "min_interval"

DEFAULT_PORT = 4196
DEFAULT_MIN_INTERVAL = 30  # seconds between writes of high-frequency values

# A slave is considered unavailable if no frame involving it is seen for this long
STALE_AFTER = 30.0
# Reconnect if the TCP socket stays silent for this long
READ_TIMEOUT = 60.0
CONNECT_TIMEOUT = 10.0
RECONNECT_MIN = 5.0
RECONNECT_MAX = 60.0
# Entities are refreshed at most once per this interval while frames arrive
DISPATCH_DELAY = 1.0
# Watchdog period used to flag stale data when the bus goes silent
WATCHDOG_INTERVAL = 10.0

MANUFACTURER = "Beretta"


def signal_update(entry_id: str) -> str:
    """Dispatcher signal fired when new bus data is available."""
    return f"{DOMAIN}_{entry_id}_update"
