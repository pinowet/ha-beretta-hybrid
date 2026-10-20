"""TCP listener for the Waveshare RS485-to-Ethernet gateway.

The connection is strictly receive-only: nothing is ever written to the socket,
so the gateway never transmits on the RS485 bus and the Hi,Comfort T300 stays
the only Modbus master.
"""

from __future__ import annotations

import asyncio
import logging
import time

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_send

from .const import (
    CONNECT_TIMEOUT,
    DISPATCH_DELAY,
    READ_TIMEOUT,
    RECONNECT_MAX,
    RECONNECT_MIN,
    STALE_AFTER,
    WATCHDOG_INTERVAL,
    signal_update,
)
from .protocol import BusState, FrameParser

_LOGGER = logging.getLogger(__name__)


async def async_test_connection(host: str, port: int) -> None:
    """Open and immediately close a TCP connection (raises OSError on failure)."""
    _reader, writer = await asyncio.wait_for(
        asyncio.open_connection(host, port), timeout=CONNECT_TIMEOUT
    )
    writer.close()
    try:
        await writer.wait_closed()
    except OSError:
        pass


class BerettaHub:
    """Receive bytes from the gateway and keep the decoded bus state."""

    def __init__(self, hass: HomeAssistant, entry_id: str, host: str, port: int) -> None:
        self.hass = hass
        self.host = host
        self.port = port
        self.state = BusState()
        self.parser = FrameParser(self.state)
        self.connected = False
        self.connections = 0
        self._signal = signal_update(entry_id)
        self._task: asyncio.Task | None = None
        self._watchdog: asyncio.Task | None = None
        self._dispatch_handle: asyncio.TimerHandle | None = None
        self._stopping = False

    # ---------------------------------------------------------------- status
    def slave_available(self, slave: int) -> bool:
        """True if a frame involving the slave was seen recently."""
        last = self.state.last_seen.get(slave)
        return last is not None and time.time() - last < STALE_AFTER

    @property
    def bus_alive(self) -> bool:
        """True if any valid frame was received recently."""
        last = self.state.last_frame
        return last is not None and time.time() - last < STALE_AFTER

    # ------------------------------------------------------------- lifecycle
    def start(self) -> None:
        """Start the listener and the watchdog as background tasks."""
        self._stopping = False
        self._task = self.hass.async_create_background_task(
            self._run(), f"beretta_hybrid listener {self.host}:{self.port}"
        )
        self._watchdog = self.hass.async_create_background_task(
            self._run_watchdog(), "beretta_hybrid watchdog"
        )

    async def stop(self) -> None:
        """Stop all background work."""
        self._stopping = True
        if self._dispatch_handle is not None:
            self._dispatch_handle.cancel()
            self._dispatch_handle = None
        for task in (self._task, self._watchdog):
            if task is not None:
                task.cancel()
        for task in (self._task, self._watchdog):
            if task is not None:
                try:
                    await task
                except asyncio.CancelledError:
                    pass
        self._task = self._watchdog = None

    # ---------------------------------------------------------------- loops
    async def _run(self) -> None:
        delay = RECONNECT_MIN
        while not self._stopping:
            writer: asyncio.StreamWriter | None = None
            try:
                reader, writer = await asyncio.wait_for(
                    asyncio.open_connection(self.host, self.port), timeout=CONNECT_TIMEOUT
                )
                self.connected = True
                self.connections += 1
                self.parser.reset()
                _LOGGER.info("Connected to %s:%s (receive only)", self.host, self.port)
                delay = RECONNECT_MIN
                while True:
                    # Receive only: no write() call exists anywhere in this module
                    data = await asyncio.wait_for(reader.read(4096), timeout=READ_TIMEOUT)
                    if not data:
                        _LOGGER.warning("Connection closed by %s:%s", self.host, self.port)
                        break
                    frames_before = self.state.frames
                    self.parser.feed(data)
                    if self.state.frames != frames_before:
                        self._schedule_dispatch()
            except asyncio.CancelledError:
                raise
            except TimeoutError:
                _LOGGER.warning(
                    "No data from %s:%s for %ss, reconnecting", self.host, self.port, READ_TIMEOUT
                )
            except OSError as err:
                _LOGGER.warning("Cannot reach %s:%s: %s", self.host, self.port, err)
            finally:
                self.connected = False
                if writer is not None:
                    writer.close()
            if self._stopping:
                break
            self._dispatch()
            await asyncio.sleep(delay)
            delay = min(delay * 2, RECONNECT_MAX)

    async def _run_watchdog(self) -> None:
        was_alive = False
        while True:
            await asyncio.sleep(WATCHDOG_INTERVAL)
            alive = self.bus_alive
            # Push availability changes (and pending throttled values) to entities
            if alive or was_alive:
                self._dispatch()
            was_alive = alive

    # --------------------------------------------------------------- dispatch
    @callback
    def _schedule_dispatch(self) -> None:
        if self._dispatch_handle is None:
            self._dispatch_handle = self.hass.loop.call_later(DISPATCH_DELAY, self._dispatch)

    @callback
    def _dispatch(self) -> None:
        self._dispatch_handle = None
        async_dispatcher_send(self.hass, self._signal)
