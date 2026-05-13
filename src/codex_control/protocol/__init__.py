"""Wire-level types for the Codex app-server JSON-RPC protocol.

This subpackage holds *only* the protocol surface: method-name constants,
JSON-RPC envelope helpers, and TypedDict / dataclass shapes for the
payloads we touch. It deliberately has no I/O — making it safe to import
from anywhere, including tests that don't link a transport.

If you find yourself reaching for a magic string like ``"turn/start"``
in higher-level code, add it to :mod:`codex_control.protocol.methods`
instead. The schemas in ``vendor/codex/.../schemas/v2`` are the source
of truth; this module is the curated Python view of what we use.
"""

from .jsonrpc import JsonRpcFrame, build_notification, build_request, parse_frame
from .methods import M, Notif
from .types import (
    ApprovalDecision,
    Item,
    ItemType,
    SandboxMode,
    TokenUsage,
    Turn,
    TurnInput,
    TurnStatus,
)

__all__ = [
    "ApprovalDecision",
    "Item",
    "ItemType",
    "JsonRpcFrame",
    "M",
    "Notif",
    "SandboxMode",
    "TokenUsage",
    "Turn",
    "TurnInput",
    "TurnStatus",
    "build_notification",
    "build_request",
    "parse_frame",
]
