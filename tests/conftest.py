"""Shared fixtures."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Enable custom integrations in every test."""
    return


def load_stream(name: str) -> bytes:
    """Concatenate the frames of a capture fixture into a raw byte stream."""
    lines = (FIXTURES / f"{name}.hex").read_text().split("\n")
    return b"".join(bytes.fromhex(line) for line in lines if line.strip())


class FakeGateway:
    """TCP server imitating the Waveshare gateway; records anything it receives."""

    def __init__(self, stream: bytes, repeat: int = 3) -> None:
        self.stream = stream
        self.repeat = repeat
        self.received = bytearray()
        self.clients = 0
        self.server: asyncio.Server | None = None
        self.port = 0

    async def _handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        self.clients += 1

        async def drain_input() -> None:
            while data := await reader.read(1024):
                self.received.extend(data)

        listener = asyncio.ensure_future(drain_input())
        try:
            for _ in range(self.repeat):
                for i in range(0, len(self.stream), 37):
                    writer.write(self.stream[i : i + 37])
                    await writer.drain()
                await asyncio.sleep(0.05)
            await asyncio.sleep(30)
        except (ConnectionError, asyncio.CancelledError):
            pass
        finally:
            listener.cancel()
            writer.close()

    async def start(self) -> None:
        self.server = await asyncio.start_server(self._handle, "127.0.0.1", 0)
        self.port = self.server.sockets[0].getsockname()[1]

    async def stop(self) -> None:
        if self.server:
            self.server.close()


@pytest.fixture
async def gateway_factory() -> AsyncIterator:
    created: list[FakeGateway] = []

    async def factory(name: str) -> FakeGateway:
        gw = FakeGateway(load_stream(name))
        await gw.start()
        created.append(gw)
        return gw

    yield factory
    for gw in created:
        await gw.stop()
