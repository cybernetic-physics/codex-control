"""The :class:`Transport` abstract base.

A transport is a thin wrapper around a bidirectional stream of
JSON-encoded objects. It exposes three methods and that's it:

* ``send(frame)`` — write one JSON object outbound.
* ``__aiter__`` — yield JSON objects as they arrive inbound.
* ``close()`` — release any underlying resources.

The session layer above (:class:`codex_control.session.CodexSession`)
owns request/response correlation, notification fan-out, approval
routing, and the typed surface. The transport is intentionally dumb so
that swapping it (stdio → ws → tests) costs nothing.
"""

from __future__ import annotations

import abc
from typing import AsyncIterator

from ..protocol.jsonrpc import JsonObject


class Transport(abc.ABC):
    """Abstract base class for bidirectional JSON-object streams."""

    @abc.abstractmethod
    async def send(self, frame: JsonObject) -> None:
        """Serialize ``frame`` and write it outbound."""

    @abc.abstractmethod
    def __aiter__(self) -> AsyncIterator[JsonObject]:
        """Async-iterate inbound frames.

        Stops cleanly when the peer closes. Should not raise on EOF;
        callers handle "stream ended" by detecting that the iterator
        finished, not by catching an exception.
        """

    @abc.abstractmethod
    async def close(self) -> None:
        """Release the transport. Safe to call more than once."""

    async def __aenter__(self) -> "Transport":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self.close()
