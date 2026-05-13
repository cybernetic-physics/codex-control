"""Approval handlers.

When Codex runs with ``approvalPolicy="on-request"`` (or older
equivalents) it sends a JSON-RPC *request* to the client whenever the
agent wants to run a shell command or apply a patch. The client must
reply with a decision or the turn stalls.

The :class:`ApprovalHandler` protocol is the extension point. Three
batteries-included handlers cover the common cases; everything else is
a 10-line subclass.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Iterable, Protocol, Sequence

from .protocol.methods import ServerReq

log = logging.getLogger(__name__)


class ApprovalHandler(Protocol):
    """Decide what to reply to a server-initiated approval request.

    Implementations receive ``(method, params)`` and return either a
    bare decision string (``"accept"``, ``"acceptForSession"``,
    ``"decline"``) or a full reply dict. The session normalises strings
    to dicts; both forms are accepted.
    """

    def __call__(self, method: str, params: dict[str, Any]) -> str | dict[str, Any]: ...


# --- Built-in handlers --------------------------------------------------

class AlwaysDecline:
    """Reject everything. The safest default (and what the session uses
    when no handler is configured)."""

    def __call__(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        return {"decision": "decline"}


class AlwaysAccept:
    """Approve everything. For trusted/sandboxed environments only."""

    def __call__(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        if method == ServerReq.APPLY_PATCH_APPROVAL:
            return {"decision": "approved"}
        return {"decision": "acceptForSession"}


class RegexGate:
    """Regex-driven allow/deny gate for shell command approvals.

    Patterns are applied in order. The first ``deny`` match wins; if no
    ``deny`` matches, the first ``allow`` decides; otherwise the
    ``default`` decision is returned.

    File-change approvals are auto-accepted (we assume the workspace
    cwd is sacrificial). Override :meth:`decide_file_change` if you
    want stricter behaviour.
    """

    def __init__(
        self,
        *,
        deny: Sequence[str] | Sequence[re.Pattern[str]] = (),
        allow: Sequence[str] | Sequence[re.Pattern[str]] = (),
        default: str = "accept",
        accept_for_session: bool = True,
    ) -> None:
        self._deny = [self._compile(p) for p in deny]
        self._allow = [self._compile(p) for p in allow]
        self._default = default
        self._accept_for_session = accept_for_session

    @staticmethod
    def _compile(p: str | re.Pattern[str]) -> re.Pattern[str]:
        return p if isinstance(p, re.Pattern) else re.compile(p)

    def _stringify(self, cmd: Any) -> str:
        if isinstance(cmd, list):
            return " ".join(str(x) for x in cmd)
        return str(cmd or "")

    def decide_command(self, command: str) -> tuple[str, str]:
        for p in self._deny:
            if p.search(command):
                return "decline", f"matched deny {p.pattern!r}"
        for p in self._allow:
            if p.search(command):
                return ("acceptForSession" if self._accept_for_session else "accept",
                        f"matched allow {p.pattern!r}")
        return self._default, "no rule matched"

    def decide_file_change(self, params: dict[str, Any]) -> str:
        return "accept"

    def __call__(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        if method == ServerReq.COMMAND_EXECUTION_REQUEST_APPROVAL:
            cmd = self._stringify(params.get("command"))
            decision, reason = self.decide_command(cmd)
            log.debug("RegexGate: cmd=%r -> %s (%s)", cmd[:120], decision, reason)
            return {"decision": decision}
        if method == ServerReq.FILE_CHANGE_REQUEST_APPROVAL:
            return {"decision": self.decide_file_change(params)}
        if method in (ServerReq.EXEC_COMMAND_APPROVAL, ServerReq.APPLY_PATCH_APPROVAL):
            return {"decision": "approved"}
        return {"decision": "decline"}


class Composed:
    """Try handlers in order; first non-``None`` reply wins.

    Useful to layer policy: e.g. a strict :class:`RegexGate` first, then
    a permissive :class:`AlwaysAccept` fallback for paths not covered.
    """

    def __init__(self, handlers: Iterable[ApprovalHandler]) -> None:
        self._handlers = list(handlers)

    def __call__(self, method: str, params: dict[str, Any]) -> dict[str, Any] | str:
        last: dict[str, Any] | str = {"decision": "decline"}
        for h in self._handlers:
            res = h(method, params)
            if res is None:
                continue
            last = res
            # First handler that returns *any* decision wins.
            return res
        return last
