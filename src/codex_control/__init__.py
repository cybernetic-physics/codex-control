"""codex-control — async Python library for puppeteering ``codex app-server``.

The library is organised around four layers, each importable directly:

============================ =============================================
:mod:`codex_control.protocol` Wire types and method-name constants
:mod:`codex_control.transport` ``StdioTransport`` / ``WebSocketTransport``
:mod:`codex_control.session`   :class:`CodexSession` — JSON-RPC dispatcher
:mod:`codex_control.thread`    :class:`Thread` — high-level thread facade
============================ =============================================

On top of those we ship RL-shaped helpers:

* :mod:`codex_control.budget`     — :class:`Budget` + :class:`BudgetSteerWatcher`
* :mod:`codex_control.handlers`   — approval-handler protocol + ``RegexGate``
* :mod:`codex_control.traces`     — :class:`TraceWriter`
* :mod:`codex_control.introspect` — capability dossier

Five-package refactor note: as of v0.1, parallel-rollout running,
fork-based tree search, RLVR episodes, and the verifier batteries moved
to sibling packages (``codex_orchestrate`` and ``codex_env``). The
legacy ``rollouts.grpo_advantage`` math and ``verifiers`` shim re-exports
remain here for one release of grace.

Typical usage::

    import asyncio
    from codex_control import CodexSession

    async def main():
        async with CodexSession.spawn() as session:
            thread = await session.start_thread()
            turn = await thread.run_turn("Reply with: pong")
            print(turn.final_text)
            await thread.archive()

    asyncio.run(main())
"""

from __future__ import annotations

from typing import Any

from ._version import __version__
from .budget import (
    Budget,
    BudgetSteerWatcher,
    DEFAULT_STEER_PROMPT,
    make_token_usage_callback,
)
from .errors import (
    BudgetExceeded,
    CodexControlError,
    HandshakeError,
    ProtocolError,
    RpcError,
    TransportError,
    TurnFailed,
)
from .handlers import (
    AlwaysAccept,
    AlwaysDecline,
    ApprovalHandler,
    Composed,
    RegexGate,
)
from .introspect import CapabilityDossier, fetch_dossier
from .items import (
    command_executions,
    command_string,
    file_changes,
    final_text,
    item_type_counts,
    items_of_type,
    last_agent_message,
    summarise,
)
from .protocol import (
    ApprovalDecision,
    Item,
    ItemType,
    M,
    Notif,
    SandboxMode,
    TokenUsage,
    Turn,
    TurnInput,
    TurnStatus,
)
from .rollouts import (
    GroupStats,
    RolloutResult,
    grpo_advantage,
)
from .session import CodexSession, Subscription
from .thread import Thread, build_demo_pair, build_developer_hint
from .transport import StdioTransport, Transport
from .traces import TraceWriter, write_group_json, write_turn_jsonl
from .turn import TurnHandle, collect_turn

_VERIFIER_EXPORTS = {
    "CompositeVerifier",
    "JsonSchemaVerifier",
    "PytestVerifier",
    "RegexVerifier",
    "SubprocessVerifier",
    "Verifier",
    "VerifierResult",
}


def __getattr__(name: str) -> Any:
    """Lazy-load verifier compatibility exports.

    Core app-server control should not require ``codex_env``. The verifier
    names remain available from ``codex_control`` when the compatibility extra
    is installed, but importing ``codex_control.CodexSession`` stays lean.
    """
    if name not in _VERIFIER_EXPORTS:
        raise AttributeError(f"module 'codex_control' has no attribute {name!r}")
    try:
        from . import verifiers as _verifiers
    except ModuleNotFoundError as exc:
        if exc.name and exc.name.startswith("codex_env"):
            raise ImportError(
                f"codex_control.{name} requires codex_env. Install verifier "
                "compatibility extras with: pip install 'codex-control[verifiers-compat]'"
            ) from exc
        raise
    value = getattr(_verifiers, name)
    globals()[name] = value
    return value

__all__ = [
    # version
    "__version__",
    # core
    "CodexSession",
    "Subscription",
    "Thread",
    "TurnHandle",
    "Turn",
    "collect_turn",
    # transports
    "Transport",
    "StdioTransport",
    # protocol
    "M",
    "Notif",
    "ItemType",
    "Item",
    "TokenUsage",
    "TurnInput",
    "TurnStatus",
    "SandboxMode",
    "ApprovalDecision",
    # items
    "final_text",
    "last_agent_message",
    "items_of_type",
    "command_executions",
    "file_changes",
    "command_string",
    "item_type_counts",
    "summarise",
    # handlers
    "ApprovalHandler",
    "AlwaysAccept",
    "AlwaysDecline",
    "RegexGate",
    "Composed",
    # budget
    "Budget",
    "BudgetSteerWatcher",
    "DEFAULT_STEER_PROMPT",
    "make_token_usage_callback",
    # rollouts (legacy — moves to codex-train in Phase 4)
    "RolloutResult",
    "GroupStats",
    "grpo_advantage",
    # verifiers (legacy — re-exported from codex_env for one release)
    "Verifier",
    "VerifierResult",
    "RegexVerifier",
    "JsonSchemaVerifier",
    "SubprocessVerifier",
    "PytestVerifier",
    "CompositeVerifier",
    # introspection
    "CapabilityDossier",
    "fetch_dossier",
    # inject_items helpers
    "build_developer_hint",
    "build_demo_pair",
    # traces
    "TraceWriter",
    "write_turn_jsonl",
    "write_group_json",
    # errors
    "CodexControlError",
    "TransportError",
    "ProtocolError",
    "RpcError",
    "HandshakeError",
    "TurnFailed",
    "BudgetExceeded",
]
