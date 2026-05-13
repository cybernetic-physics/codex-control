"""Pytest fixtures plus a deterministic in-memory transport.

The fake transport lets us exercise the entire dispatch loop —
handshake, request/response correlation, server-initiated approval
requests, notifications, error propagation — without ever launching a
real ``codex app-server``.
"""

from __future__ import annotations

import asyncio
import logging
from typing import AsyncIterator, Awaitable, Callable, Optional

import pytest

from codex_control.protocol.jsonrpc import JsonObject
from codex_control.transport.base import Transport

logging.basicConfig(level=logging.DEBUG)


class FakeTransport(Transport):
    """In-memory transport that lets a test script the server side.

    On every outbound frame the test's ``handler`` is awaited; whatever
    it produces (a single frame, an iterable of frames, or None) is
    enqueued onto the inbound side.

    The handler signature::

        async def handler(sent_frame, transport) -> list[JsonObject] | None

    ``transport.push(frame)`` is also available so a handler can inject
    asynchronous notifications.
    """

    def __init__(
        self,
        handler: Optional[Callable[["FakeTransport", JsonObject], Awaitable[None]]] = None,
    ) -> None:
        self._handler = handler
        self._inbound: asyncio.Queue[Optional[JsonObject]] = asyncio.Queue()
        self.sent: list[JsonObject] = []
        self._closed = False

    async def start(self) -> None:
        return None

    async def send(self, frame: JsonObject) -> None:
        self.sent.append(frame)
        if self._handler is not None:
            await self._handler(self, frame)

    async def push(self, frame: JsonObject) -> None:
        await self._inbound.put(frame)

    def push_nowait(self, frame: JsonObject) -> None:
        self._inbound.put_nowait(frame)

    async def __aiter__(self) -> AsyncIterator[JsonObject]:
        while True:
            frame = await self._inbound.get()
            if frame is None:
                return
            yield frame

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        await self._inbound.put(None)


@pytest.fixture
def fake_transport_factory():
    """Factory fixture: build a fake transport with a custom handler."""

    def _make(handler=None) -> FakeTransport:
        return FakeTransport(handler=handler)

    return _make
