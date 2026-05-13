""":class:`Thread` — high-level handle for one ``thread/start`` worth of state.

Most user code talks to :class:`Thread`, not :class:`CodexSession`
directly: you get one back from
:meth:`CodexSession.start_thread() <codex_control.session.CodexSession.start_thread>`
or :meth:`CodexSession.fork() <codex_control.session.CodexSession>`.

Why this exists: every verb in the protocol that names a thread
(``thread/fork``, ``thread/archive``, ``thread/rollback``,
``thread/inject_items``, ``thread/read``, ``thread/turns/list``,
``thread/setName``, ``turn/start``) takes the same ``threadId`` field.
Wrapping that in an object instead of threading a string through every
call eliminates a category of bugs (typo'd ids, off-by-one when forking
from a wrong parent) and makes the call sites read like Python.
"""

from __future__ import annotations

import contextlib
import dataclasses
import logging
from typing import Any, Optional, TYPE_CHECKING

from .errors import RpcError
from .protocol.jsonrpc import JsonObject
from .protocol.methods import M
from .protocol.types import Turn
from .turn import TurnHandle, collect_turn

if TYPE_CHECKING:
    from .session import CodexSession

log = logging.getLogger(__name__)


@dataclasses.dataclass
class Thread:
    """High-level wrapper around one thread id."""

    session: "CodexSession"
    thread_id: str
    ephemeral: bool = True
    meta: dict[str, Any] = dataclasses.field(default_factory=dict)
    _closed: bool = dataclasses.field(default=False, init=False, repr=False)

    # --- construction helpers ----------------------------------------

    @classmethod
    def from_start_result(
        cls,
        session: "CodexSession",
        thread_start_result: JsonObject,
    ) -> "Thread":
        thread = thread_start_result.get("thread") or {}
        return cls(
            session=session,
            thread_id=str(thread.get("id") or thread_start_result.get("threadId") or ""),
            ephemeral=bool(thread.get("ephemeral", True)),
            meta=dict(thread),
        )

    # --- turn lifecycle ----------------------------------------------

    async def start_turn(
        self,
        prompt: str,
        *,
        cwd: Optional[str] = None,
        model: Optional[str] = None,
        effort: Optional[str] = None,
        approval_policy: Optional[str] = None,
        sandbox_policy: Optional[JsonObject] = None,
        output_schema: Optional[JsonObject] = None,
        input_extra: Optional[list[JsonObject]] = None,
        extra: Optional[JsonObject] = None,
    ) -> TurnHandle:
        """Fire ``turn/start`` and return a live handle.

        The subscription is registered *before* the request is sent, so
        no early ``item/started`` / ``item/completed`` notification is
        ever missed. Pair this with :func:`~codex_control.turn.collect_turn`
        when you want to receive the stream, or with :meth:`run_turn`
        when you want both in one call.
        """
        sub = self.session.subscribe()
        inputs: list[JsonObject] = [{"type": "text", "text": prompt}]
        if input_extra:
            inputs.extend(input_extra)
        params: JsonObject = {
            "threadId": self.thread_id,
            "input": inputs,
        }
        if cwd is not None:
            params["cwd"] = cwd
        if model is not None:
            params["model"] = model
        if effort is not None:
            params["effort"] = effort
        if approval_policy is not None:
            params["approvalPolicy"] = approval_policy
        if sandbox_policy is not None:
            params["sandboxPolicy"] = sandbox_policy
        if output_schema is not None:
            params["outputSchema"] = output_schema
        if extra:
            params.update(extra)

        try:
            res = await self.session.request(M.TURN_START, params)
        except Exception:
            sub.close()
            raise
        turn_id = str(res.get("turn", {}).get("id") or res.get("turnId") or "")
        return TurnHandle(
            session=self.session,
            thread_id=self.thread_id,
            turn_id=turn_id,
            subscription=sub,
        )

    async def run_turn(
        self,
        prompt: str,
        *,
        cwd: Optional[str] = None,
        model: Optional[str] = None,
        effort: Optional[str] = None,
        approval_policy: Optional[str] = None,
        sandbox_policy: Optional[JsonObject] = None,
        output_schema: Optional[JsonObject] = None,
        timeout: float = 300.0,
        on_item: Any = None,
        on_notification: Any = None,
        interrupt_after_items: Optional[int] = None,
        input_extra: Optional[list[JsonObject]] = None,
        extra: Optional[JsonObject] = None,
    ) -> Turn:
        """Fire a turn and drain it to completion.

        Returns a :class:`Turn`. This is the workhorse — use it unless
        you need to interleave ``turn/steer`` between subscribe and
        collect, in which case :meth:`start_turn` + a manual
        :func:`~codex_control.turn.collect_turn` is the right pattern.
        """
        handle = await self.start_turn(
            prompt,
            cwd=cwd,
            model=model,
            effort=effort,
            approval_policy=approval_policy,
            sandbox_policy=sandbox_policy,
            output_schema=output_schema,
            input_extra=input_extra,
            extra=extra,
        )
        async with handle.subscription:
            return await collect_turn(
                handle,
                on_item=on_item,
                on_notification=on_notification,
                interrupt_after_items=interrupt_after_items,
                timeout=timeout,
            )

    # --- thread verbs -------------------------------------------------

    async def fork(self, *, ephemeral: bool = True) -> "Thread":
        """Fork this thread. The child inherits the conversation history.

        Note from the experiments: the parent must be persisted
        (``ephemeral=False``); fork from an ephemeral parent returns
        ``-32600: no rollout found for thread id``. Children can be
        ephemeral.
        """
        res = await self.session.request(
            M.THREAD_FORK,
            {"threadId": self.thread_id, "ephemeral": ephemeral},
        )
        return Thread.from_start_result(self.session, res)

    async def rollback(self, num_turns: int) -> dict[str, Any]:
        """Drop the last ``num_turns`` turns from the thread's history.

        Does *not* undo on-disk file changes — that's the caller's job
        (e.g. ``git reset --hard``). The schema is explicit about this.
        """
        return await self.session.request(
            M.THREAD_ROLLBACK,
            {"threadId": self.thread_id, "numTurns": num_turns},
        )

    async def inject_items(self, items: list[JsonObject]) -> dict[str, Any]:
        """Append raw Responses-API items to the thread's history.

        The items list is passed through verbatim; Codex doesn't
        validate it. Wrong shape → silently dropped. See
        :func:`build_demo_pair` / :func:`build_developer_hint` below for
        the supported shapes.
        """
        return await self.session.request(
            M.THREAD_INJECT_ITEMS,
            {"threadId": self.thread_id, "items": items},
        )

    async def read(self) -> dict[str, Any]:
        return await self.session.request(
            M.THREAD_READ, {"threadId": self.thread_id}
        )

    async def turns_list(self) -> dict[str, Any]:
        return await self.session.request(
            M.THREAD_TURNS_LIST, {"threadId": self.thread_id}
        )

    async def set_name(self, name: str) -> dict[str, Any]:
        return await self.session.request(
            M.THREAD_SET_NAME, {"threadId": self.thread_id, "name": name}
        )

    async def compact(self) -> dict[str, Any]:
        return await self.session.request(
            M.THREAD_COMPACT_START, {"threadId": self.thread_id}
        )

    async def archive(self) -> None:
        """Archive the thread. Silent no-op if the thread is ephemeral.

        Calling archive on an ephemeral thread returns
        ``-32600 "no rollout found"`` because there's no on-disk rollout
        to mark archived. We swallow that error so callers can call
        archive unconditionally in cleanup paths.
        """
        if self._closed:
            return
        self._closed = True
        try:
            await self.session.request(
                M.THREAD_ARCHIVE, {"threadId": self.thread_id}
            )
        except RpcError as exc:
            log.debug("archive(%s) suppressed: %s", self.thread_id, exc)

    # --- async context manager ---------------------------------------

    async def __aenter__(self) -> "Thread":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        with contextlib.suppress(Exception):
            await self.archive()


# -----------------------------------------------------------------------
# inject_items helpers
# -----------------------------------------------------------------------

def build_developer_hint(text: str) -> JsonObject:
    """Build a developer-role message item for :meth:`Thread.inject_items`."""
    return {
        "type": "message",
        "role": "developer",
        "content": [{"type": "input_text", "text": text}],
    }


def build_demo_pair(user_text: str, assistant_text: str) -> list[JsonObject]:
    """Build a paired user+assistant exchange (few-shot demonstration)."""
    return [
        {
            "type": "message",
            "role": "user",
            "content": [{"type": "input_text", "text": user_text}],
        },
        {
            "type": "message",
            "role": "assistant",
            "content": [{"type": "output_text", "text": assistant_text}],
        },
    ]
