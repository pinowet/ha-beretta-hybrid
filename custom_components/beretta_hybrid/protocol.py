"""Passive Modbus RTU sniffer core for the Beretta hybrid bus.

Pure Python, no Home Assistant imports, so it can be tested offline.

The Hi,Comfort T300 is the only Modbus master on the RS485 bus. This module
only *decodes* the bytes it receives: it never produces data to transmit.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field

# Register tables as seen on the bus
TABLE_COIL = "c"  # FC1 read / FC5, FC15 write
TABLE_DISCRETE = "d"  # FC2 read
TABLE_HOLDING = "h"  # FC3 read (value reported by the slave)
TABLE_INPUT = "i"  # FC4 read
TABLE_WRITTEN = "w"  # FC6 / FC16 write (value sent by the master)

_READ_TABLE = {1: TABLE_COIL, 2: TABLE_DISCRETE, 3: TABLE_HOLDING, 4: TABLE_INPUT}

# Frame kinds
REQUEST = "request"
RESPONSE = "response"
WRITE = "write"
WRITE_ACK = "write_ack"
EXCEPTION = "exception"

MAX_FRAME = 256
_MAX_BUFFER = 4096


def crc16(data: bytes | bytearray | memoryview) -> int:
    """Modbus RTU CRC16."""
    crc = 0xFFFF
    for byte in data:
        crc ^= byte
        for _ in range(8):
            crc = (crc >> 1) ^ 0xA001 if crc & 1 else crc >> 1
    return crc


def crc_ok(frame: bytes | bytearray | memoryview) -> bool:
    """Return True if the last two bytes are a valid CRC of the frame."""
    if len(frame) < 4:
        return False
    crc = crc16(frame[:-2])
    return frame[-2] == (crc & 0xFF) and frame[-1] == (crc >> 8)


def s16(value: int) -> int:
    """Interpret an unsigned 16-bit value as signed."""
    return value - 0x10000 if value >= 0x8000 else value


@dataclass
class BusState:
    """Last known value of every register observed on the bus."""

    # (slave, table, register) -> (value_u16, timestamp)
    registers: dict[tuple[int, str, int], tuple[int, float]] = field(default_factory=dict)
    # slave -> timestamp of the last frame addressed to/from it
    last_seen: dict[int, float] = field(default_factory=dict)
    # (slave, table, start) -> timestamp of the last bulk write by the master
    block_writes: dict[tuple[int, str, int], float] = field(default_factory=dict)
    last_frame: float | None = None
    frames: int = 0
    bytes_received: int = 0
    bytes_discarded: int = 0
    unmatched_responses: int = 0
    exceptions: int = 0

    def get(self, slave: int, table: str, register: int) -> int | None:
        """Return the raw unsigned value of a register, or None if never seen."""
        item = self.registers.get((slave, table, register))
        return None if item is None else item[0]

    def updated(self, slave: int, table: str, register: int) -> float | None:
        """Return the timestamp of the last update of a register."""
        item = self.registers.get((slave, table, register))
        return None if item is None else item[1]


class FrameParser:
    """Rebuild Modbus RTU frames from an arbitrarily chunked byte stream.

    TCP gateways do not preserve the 3.5 character silent interval between RTU
    frames, so frame boundaries are found by trying the possible lengths for the
    function code and validating the CRC.
    """

    def __init__(
        self,
        state: BusState | None = None,
        on_frame: Callable[[str, bytes], None] | None = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.state = state or BusState()
        self._on_frame = on_frame
        self._clock = clock
        self._buf = bytearray()
        # (slave, function, start, count, raw frame) of the last master frame
        self._pending: tuple[int, int, int, int, bytes] | None = None

    def reset(self) -> None:
        """Drop partial data, e.g. after a reconnection."""
        self._buf.clear()
        self._pending = None

    def feed(self, data: bytes, ts: float | None = None) -> None:
        """Feed received bytes."""
        if not data:
            return
        ts = self._clock() if ts is None else ts
        self.state.bytes_received += len(data)
        self._buf.extend(data)
        used = self._parse(ts)
        if used:
            del self._buf[:used]
        if len(self._buf) > _MAX_BUFFER:
            self.state.bytes_discarded += len(self._buf)
            self._buf.clear()

    # ------------------------------------------------------------------ parse
    def _candidates(self, i: int) -> list[tuple[str, int | None]]:
        buf = self._buf
        avail = len(buf) - i
        addr, fc = buf[i], buf[i + 1]
        if addr > 247:
            return []
        if fc in (1, 2, 3, 4):
            return [(REQUEST, 8), (RESPONSE, 5 + buf[i + 2])]
        if fc in (5, 6):
            return [(WRITE, 8)]
        if fc in (15, 16):
            return [(WRITE_ACK, 8), (WRITE, 9 + buf[i + 6] if avail >= 7 else None)]
        if fc >= 0x80 and (fc & 0x7F) in (1, 2, 3, 4, 5, 6, 15, 16):
            return [(EXCEPTION, 5)]
        return []

    def _choose(self, valid: list[tuple[str, int]], i: int) -> tuple[str, int]:
        if len(valid) == 1:
            return valid[0]
        kinds = dict(valid)
        addr, fc = self._buf[i], self._buf[i + 1]
        pending = self._pending
        if pending and pending[0] == addr and pending[1] == fc:
            for kind in (RESPONSE, WRITE_ACK):
                if kind in kinds:
                    return kind, kinds[kind]
        return valid[0]

    def _parse(self, ts: float) -> int:
        buf = self._buf
        size = len(buf)
        i = 0
        while size - i >= 4:
            valid: list[tuple[str, int]] = []
            need_more = False
            for kind, length in self._candidates(i):
                if length is None or i + length > size:
                    need_more = True
                    continue
                if length <= MAX_FRAME and crc_ok(memoryview(buf)[i : i + length]):
                    valid.append((kind, length))
            if valid:
                kind, length = self._choose(valid, i)
                self._handle(kind, bytes(buf[i : i + length]), ts)
                i += length
                continue
            if need_more and size - i < MAX_FRAME + 44:
                break
            i += 1
            self.state.bytes_discarded += 1
        return i

    # ----------------------------------------------------------------- decode
    def _store(self, slave: int, table: str, reg: int, value: int, ts: float) -> None:
        self.state.registers[(slave, table, reg)] = (value, ts)

    def _handle(self, kind: str, f: bytes, ts: float) -> None:
        st = self.state
        addr, fc = f[0], f[1]
        st.frames += 1
        st.last_frame = ts
        st.last_seen[addr] = ts

        if fc in (5, 6) and self._pending and self._pending[4] == f:
            kind = WRITE_ACK  # echo of a single write

        if kind == REQUEST:
            start, count = (f[2] << 8) | f[3], (f[4] << 8) | f[5]
            self._pending = (addr, fc, start, count, f)

        elif kind == RESPONSE:
            pending, self._pending = self._pending, None
            if not pending or pending[0] != addr or pending[1] != fc:
                st.unmatched_responses += 1
            else:
                start, count, nbytes = pending[2], pending[3], f[2]
                data = f[3 : 3 + nbytes]
                table = _READ_TABLE[fc]
                if fc in (3, 4):
                    if nbytes != 2 * count:
                        st.unmatched_responses += 1
                    else:
                        for k in range(count):
                            value = (data[2 * k] << 8) | data[2 * k + 1]
                            self._store(addr, table, start + k, value, ts)
                else:
                    for k in range(count):
                        if k // 8 < nbytes:
                            self._store(addr, table, start + k, (data[k // 8] >> (k % 8)) & 1, ts)

        elif kind == WRITE:
            if fc == 6:
                self._store(addr, TABLE_WRITTEN, (f[2] << 8) | f[3], (f[4] << 8) | f[5], ts)
            elif fc == 5:
                self._store(addr, TABLE_COIL, (f[2] << 8) | f[3], 1 if f[4] == 0xFF else 0, ts)
            elif fc == 16:
                start, count = (f[2] << 8) | f[3], (f[4] << 8) | f[5]
                for k in range(count):
                    self._store(
                        addr, TABLE_WRITTEN, start + k, (f[7 + 2 * k] << 8) | f[8 + 2 * k], ts
                    )
                st.block_writes[(addr, TABLE_WRITTEN, start)] = ts
            elif fc == 15:
                start, count = (f[2] << 8) | f[3], (f[4] << 8) | f[5]
                data = f[7 : 7 + f[6]]
                for k in range(count):
                    self._store(addr, TABLE_COIL, start + k, (data[k // 8] >> (k % 8)) & 1, ts)
            self._pending = (addr, fc, 0, 0, f)

        elif kind == WRITE_ACK:
            self._pending = None

        elif kind == EXCEPTION:
            st.exceptions += 1
            self._pending = None

        if self._on_frame is not None:
            self._on_frame(kind, f)
