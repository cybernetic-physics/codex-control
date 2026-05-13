"""Typed exception hierarchy for codex-control.

The hierarchy is intentionally narrow. Callers should be able to catch
:class:`CodexControlError` at the top level for "anything we did failed",
or one of the subclasses for a specific failure mode.

A note on :class:`RpcError`: the JSON-RPC error object travels through
the wire unchanged. We expose ``code`` (the integer), ``message`` (the
short string), ``data`` (server-defined payload, possibly ``None``), and
``method`` (the request we sent). Server-internal error codes overlap
with the standard JSON-RPC range; we don't try to map them.
"""

from __future__ import annotations

from typing import Any


class CodexControlError(Exception):
    """Base class for every error raised by this package."""


class TransportError(CodexControlError):
    """Wire-level transport failed (connection dropped, subprocess died, etc.)."""


class ProtocolError(CodexControlError):
    """Malformed or unexpected JSON-RPC frame from the peer."""


class RpcError(CodexControlError):
    """The peer answered our request with a JSON-RPC error object."""

    def __init__(
        self,
        method: str,
        code: int,
        message: str,
        data: Any | None = None,
    ) -> None:
        self.method = method
        self.code = code
        self.message = message
        self.data = data
        super().__init__(f"{method}: {code} {message}")


class HandshakeError(CodexControlError):
    """The ``initialize``/``initialized`` handshake failed."""


class TurnFailed(CodexControlError):
    """A turn ended in a non-completed state we treat as an error.

    Examples: ``turn/completed status="failed"``, an explicit ``error``
    notification on the wire, or the agent never producing
    ``turn/completed`` within the deadline.
    """

    def __init__(self, status: str, payload: dict[str, Any] | None = None) -> None:
        self.status = status
        self.payload = payload or {}
        super().__init__(f"turn ended with status={status!r}")


class BudgetExceeded(CodexControlError):
    """A budget (turns, tokens, wall-clock) was hit before success."""

    def __init__(self, kind: str, used: int | float, limit: int | float) -> None:
        self.kind = kind
        self.used = used
        self.limit = limit
        super().__init__(f"{kind} budget exceeded: used={used} limit={limit}")
