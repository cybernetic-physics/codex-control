"""WebSocket transport for remote ``codex app-server --listen ws://...``.

This transport is what makes the "trainer in one container, Codex pool
in another" deployment possible. Wire-format identical to stdio; just
the framing changes (TCP / WS message instead of newline). Capability-
token auth is set via the ``Authorization: Bearer …`` header.

The optional dependency on :mod:`websockets` is imported lazily inside
:meth:`WebSocketTransport.start`; ``import codex_control`` keeps working
on hosts that only need stdio.

Operational note from the experiments: ``codex app-server`` rejects any
WebSocket handshake that includes an ``Origin`` header (403). We rely
on :mod:`websockets`' default of not emitting an Origin on non-browser
URIs, and never add one ourselves.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
from typing import Any, AsyncIterator, Optional

from ..errors import TransportError
from ..protocol.jsonrpc import JsonObject
from .base import Transport

log = logging.getLogger(__name__)


class WebSocketTransport(Transport):
    """One ``ws://``/``wss://`` connection to a remote app-server.

    Parameters
    ----------
    url
        WebSocket URL of the remote app-server, e.g. ``ws://codex:8765``.
    token
        Capability-token bearer string. If ``None``, no Authorization
        header is sent (the server must be configured to allow that).
    connect_timeout
        Seconds to wait for the WS handshake. Defaults to 30s — generous
        because the server often blocks on its first ``initialize`` call
        and the WS upgrade can race with that.
    extra_headers
        Optional list of ``(name, value)`` tuples appended to the
        handshake. Useful for tracing/correlation headers.
    """

    def __init__(
        self,
        url: str,
        *,
        token: Optional[str] = None,
        connect_timeout: float = 30.0,
        extra_headers: Optional[list[tuple[str, str]]] = None,
    ) -> None:
        self._url = url
        self._token = token
        self._connect_timeout = connect_timeout
        self._extra_headers = list(extra_headers or [])
        self._ws: Any = None
        self._closed = False

    async def start(self) -> None:
        """Open the WebSocket and run the JSON-RPC handshake at a higher level."""
        if self._ws is not None:
            return
        try:
            import websockets  # type: ignore[import-not-found]
        except ImportError as exc:  # pragma: no cover
            raise TransportError(
                "WebSocketTransport requires the 'websockets' extra: "
                "`pip install codex-control[websocket]`"
            ) from exc

        headers: list[tuple[str, str]] = list(self._extra_headers)
        if self._token:
            headers.append(("Authorization", f"Bearer {self._token}"))

        try:
            self._ws = await asyncio.wait_for(
                websockets.connect(self._url, additional_headers=headers),
                timeout=self._connect_timeout,
            )
        except TypeError:
            # `websockets < 14` used `extra_headers=` instead.
            self._ws = await asyncio.wait_for(
                websockets.connect(self._url, extra_headers=headers),
                timeout=self._connect_timeout,
            )
        except Exception as exc:
            raise TransportError(f"failed to connect to {self._url}: {exc}") from exc

    async def __aenter__(self) -> "WebSocketTransport":
        await self.start()
        return self

    async def send(self, frame: JsonObject) -> None:
        if self._ws is None:
            raise TransportError("transport not started")
        try:
            await self._ws.send(json.dumps(frame, separators=(",", ":")))
        except Exception as exc:
            raise TransportError(f"send failed: {exc}") from exc

    async def __aiter__(self) -> AsyncIterator[JsonObject]:
        if self._ws is None:
            raise TransportError("transport not started")
        try:
            async for raw in self._ws:
                if isinstance(raw, bytes):
                    raw = raw.decode("utf-8", errors="replace")
                try:
                    obj = json.loads(raw)
                except json.JSONDecodeError as exc:
                    log.warning("dropping non-JSON ws frame: %r (%s)", raw[:200], exc)
                    continue
                if isinstance(obj, dict):
                    yield obj
                else:
                    log.warning("dropping non-object JSON ws frame: %r", raw[:200])
        except Exception as exc:  # pragma: no cover — connection-loss path
            log.info("websocket iteration ended: %s", exc)

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        if self._ws is not None:
            with contextlib.suppress(Exception):
                await self._ws.close()
