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
* :mod:`codex_control.rollouts`   — :func:`parallel_rollouts`, :func:`grpo_advantage`
* :mod:`codex_control.tree`       — fork-based tree search
* :mod:`codex_control.verifiers`  — :class:`Verifier` protocol + ``PytestVerifier``, …
* :mod:`codex_control.rlvr`       — :func:`run_rlvr_episode`
* :mod:`codex_control.handlers`   — approval-handler protocol + ``RegexGate``
* :mod:`codex_control.traces`     — :class:`TraceWriter`
* :mod:`codex_control.introspect` — capability dossier

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
from .rlvr import (
    RlvrEpisode,
    pytest_followup,
    regex_followup,
    run_rlvr_episode,
    shape_rlvr_reward,
)
from .rollouts import (
    GroupStats,
    RolloutResult,
    grpo_advantage,
    parallel_rollouts,
    single_turn_group,
)
from .session import CodexSession, Subscription
from .thread import Thread, build_demo_pair, build_developer_hint
from .transport import StdioTransport, Transport
from .traces import TraceWriter, write_group_json, write_turn_jsonl
from .tree import (
    Node,
    expand,
    expand_all,
    fork_tree_search,
    length_value,
    select_uct,
)
from .turn import TurnHandle, collect_turn
from .verifiers import (
    CompositeVerifier,
    JsonSchemaVerifier,
    PytestVerifier,
    RegexVerifier,
    SubprocessVerifier,
    Verifier,
    VerifierResult,
)

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
    # rollouts
    "RolloutResult",
    "GroupStats",
    "parallel_rollouts",
    "grpo_advantage",
    "single_turn_group",
    # tree
    "Node",
    "expand",
    "expand_all",
    "fork_tree_search",
    "length_value",
    "select_uct",
    # verifiers
    "Verifier",
    "VerifierResult",
    "RegexVerifier",
    "JsonSchemaVerifier",
    "SubprocessVerifier",
    "PytestVerifier",
    "CompositeVerifier",
    # rlvr
    "RlvrEpisode",
    "run_rlvr_episode",
    "shape_rlvr_reward",
    "pytest_followup",
    "regex_followup",
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
