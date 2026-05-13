"""Centralised method-name constants.

Putting these in one place is the single biggest defence against schema
drift: when Codex renames ``thread/tokenUsage/updated`` to something else
on a future bump (it's already a non-obvious name), we change one line
here and every call site keeps working.

The ``M`` namespace is for client→server *requests*, the ``Notif``
namespace is for server→client *notifications*. Server→client
*requests* (which our client has to answer) live in ``ServerReq``.
"""

from __future__ import annotations

from typing import Final


class M:
    """Client→server JSON-RPC methods (require a response)."""

    # Lifecycle
    INITIALIZE: Final[str] = "initialize"

    # Thread CRUD
    THREAD_START: Final[str] = "thread/start"
    THREAD_FORK: Final[str] = "thread/fork"
    THREAD_RESUME: Final[str] = "thread/resume"
    THREAD_ARCHIVE: Final[str] = "thread/archive"
    THREAD_UNARCHIVE: Final[str] = "thread/unarchive"
    THREAD_ROLLBACK: Final[str] = "thread/rollback"
    THREAD_INJECT_ITEMS: Final[str] = "thread/inject_items"
    THREAD_READ: Final[str] = "thread/read"
    THREAD_LIST: Final[str] = "thread/list"
    THREAD_TURNS_LIST: Final[str] = "thread/turns/list"
    THREAD_SET_NAME: Final[str] = "thread/setName"
    THREAD_COMPACT_START: Final[str] = "thread/compact/start"

    # Turn lifecycle
    TURN_START: Final[str] = "turn/start"
    TURN_STEER: Final[str] = "turn/steer"
    TURN_INTERRUPT: Final[str] = "turn/interrupt"

    # Introspection
    MODEL_LIST: Final[str] = "model/list"
    COLLABORATION_MODE_LIST: Final[str] = "collaborationMode/list"
    EXPERIMENTAL_FEATURE_LIST: Final[str] = "experimentalFeature/list"
    MODEL_PROVIDER_CAPABILITIES_READ: Final[str] = "modelProvider/capabilities/read"
    APP_LIST: Final[str] = "app/list"


class Notif:
    """Server→client JSON-RPC notifications (no response expected)."""

    # Lifecycle
    INITIALIZED: Final[str] = "initialized"

    # Item stream
    ITEM_STARTED: Final[str] = "item/started"
    ITEM_COMPLETED: Final[str] = "item/completed"
    AGENT_MESSAGE_DELTA: Final[str] = "agentMessageDelta"

    # Turn stream
    TURN_STARTED: Final[str] = "turn/started"
    TURN_COMPLETED: Final[str] = "turn/completed"
    TURN_DIFF_UPDATED: Final[str] = "turn/diff/updated"
    TURN_PLAN_UPDATED: Final[str] = "turn/plan/updated"

    # Thread events
    THREAD_STARTED: Final[str] = "thread/started"
    THREAD_CLOSED: Final[str] = "thread/closed"
    THREAD_ARCHIVED: Final[str] = "thread/archived"
    THREAD_UNARCHIVED: Final[str] = "thread/unarchived"
    THREAD_STATUS_CHANGED: Final[str] = "thread/statusChanged"
    THREAD_TOKEN_USAGE_UPDATED: Final[str] = "thread/tokenUsage/updated"
    CONTEXT_COMPACTED: Final[str] = "context/compacted"

    # Errors / config
    ERROR: Final[str] = "error"
    CONFIG_WARNING: Final[str] = "config/warning"
    DEPRECATION_NOTICE: Final[str] = "deprecationNotice"


class ServerReq:
    """Server→client *requests* the client must answer.

    These come over the wire as ``{"id": N, "method": "...", "params": {...}}``
    and the client has to send back a ``{"id": N, "result": {...}}``.
    The :class:`codex_control.handlers.ApprovalHandler` protocol exists
    specifically for these.
    """

    COMMAND_EXECUTION_REQUEST_APPROVAL: Final[str] = "item/commandExecution/requestApproval"
    FILE_CHANGE_REQUEST_APPROVAL: Final[str] = "item/fileChange/requestApproval"
    # Older surfaces still present in some binaries.
    EXEC_COMMAND_APPROVAL: Final[str] = "execCommandApproval"
    APPLY_PATCH_APPROVAL: Final[str] = "applyPatchApproval"
