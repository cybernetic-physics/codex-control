"""Wire transports for :class:`codex_control.session.CodexSession`.

Two are shipped:

* :class:`StdioTransport` — spawns ``codex app-server --listen stdio://``
  as a child process and frames JSON-RPC by newline. This is the path
  for local RL runs.

* :class:`WebSocketTransport` — connects to a remote
  ``codex app-server --listen ws://...`` over a single WebSocket. Lazy
  imports :mod:`websockets`; the dependency is optional.

A third transport, :class:`FakeTransport`, lives under ``tests/`` and
implements the same :class:`Transport` ABC; the session is fully testable
without spawning a real Codex.
"""

from .base import Transport
from .stdio import StdioTransport

__all__ = ["StdioTransport", "Transport", "WebSocketTransport"]


def __getattr__(name: str):
    # Lazy attribute: importing ``WebSocketTransport`` only triggers a
    # websockets import on first access. This keeps the stdio path free
    # of the optional dep.
    if name == "WebSocketTransport":
        from .websocket import WebSocketTransport

        return WebSocketTransport
    raise AttributeError(name)
