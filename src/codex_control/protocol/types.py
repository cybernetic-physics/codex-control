"""Typed Python views of the wire payloads.

We use :class:`TypedDict` (rather than ``pydantic`` or attrs) deliberately:
the wire shapes are already JSON objects and we don't want to pay a
construction tax on every notification. Where a stronger object is
useful (``Turn`` results, ``TokenUsage`` accumulator) we ship a small
frozen dataclass.

Only the fields we actually read are listed. The wire often carries more
keys and we silently ignore them — that's the right default for a
client whose schema is allowed to grow.
"""

from __future__ import annotations

import dataclasses
from typing import Any, Literal, TypedDict


# --- Enumerations --------------------------------------------------------

ApprovalPolicy = Literal["never", "on-request", "untrusted", "always"]
"""Codex's set of approval-policy modes for shell/file operations."""

SandboxMode = Literal["read-only", "workspace-write", "danger-full-access"]
"""Sandbox mode the server applies to commands/edits the agent runs."""

ReasoningEffort = Literal["minimal", "low", "medium", "high"]
"""Reasoning-effort knob passed through to the Responses API."""

TurnStatus = Literal[
    "running", "completed", "failed", "interrupted", "timed_out", "error"
]
"""Possible terminal/intermediate statuses for a turn observed on this client."""


# --- Decisions -----------------------------------------------------------

class ApprovalDecision(TypedDict, total=False):
    """Reply payload to ``item/commandExecution/requestApproval`` etc.

    The minimal viable reply is ``{"decision": "accept"}``. We also see
    ``acceptForSession`` and ``decline`` from the schemas; callers can
    add ``_handler_error`` or similar fields for diagnostics — Codex
    ignores anything it doesn't know.
    """

    decision: Literal["accept", "acceptForSession", "decline", "approved"]


# --- Items (typed union surface) ----------------------------------------

class ItemType:
    """String constants for the discriminator on ``item.type``."""

    USER_MESSAGE = "userMessage"
    AGENT_MESSAGE = "agentMessage"
    REASONING = "reasoning"
    COMMAND_EXECUTION = "commandExecution"
    FILE_CHANGE = "fileChange"
    MCP_TOOL_CALL = "mcpToolCall"
    WEB_SEARCH = "webSearch"


class Item(TypedDict, total=False):
    """Schema fragment for items returned by ``item/completed``.

    The full schema is the discriminated union in
    ``schemas/v2/Item*`` — this typed dict is the *common* shape every
    item carries plus the keys we actually inspect in helpers.
    """

    type: str
    id: str
    text: str
    content: list[Any]
    command: Any
    exitCode: int
    path: str
    kind: Any


# --- Token usage ---------------------------------------------------------

class TokenUsage(TypedDict, total=False):
    """One snapshot from ``thread/tokenUsage/updated``."""

    inputTokens: int
    outputTokens: int
    cachedInputTokens: int
    reasoningOutputTokens: int
    totalTokens: int


# --- Turn ----------------------------------------------------------------

class TurnInput(TypedDict):
    """Element of ``turn/start.input``.

    Codex accepts a list of these. The library always sends a single
    text element today; richer inputs (image refs, etc.) are passed
    through verbatim from caller code.
    """

    type: str
    text: str


@dataclasses.dataclass(slots=True)
class Turn:
    """Lightweight value object captured at the end of one turn.

    Distinct from :class:`codex_control.turn.TurnResult` which carries the
    *streaming* state. ``Turn`` is what most callers actually want: ids,
    status, items, and the raw completion payload for the curious.
    """

    thread_id: str
    turn_id: str
    status: TurnStatus
    items: list[Item] = dataclasses.field(default_factory=list)
    completion: dict[str, Any] = dataclasses.field(default_factory=dict)
    token_usage: TokenUsage | None = None

    @property
    def final_text(self) -> str:
        """Concatenated text from every ``agentMessage`` item in order."""
        pieces = [
            it.get("text", "")
            for it in self.items
            if it.get("type") == ItemType.AGENT_MESSAGE
        ]
        return "\n".join(p for p in pieces if p)

    @property
    def succeeded(self) -> bool:
        return self.status == "completed"
