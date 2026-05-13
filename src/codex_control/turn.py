"""Turn collection.

A :class:`TurnHandle` represents an in-flight turn: it owns the
subscription that streams notifications, and exposes ``steer``,
``interrupt``, ``await_completion`` methods. :func:`collect_turn`
drains the subscription into a :class:`~codex_control.protocol.types.Turn`.

Subscription ordering is important: callers should subscribe *before*
firing ``turn/start`` so the early ``item/started`` notifications are
not missed. The :meth:`Thread.start_turn` helper handles that for you.
"""

from __future__ import annotations

import asyncio
import contextlib
import dataclasses
import logging
from typing import Any, Callable, Optional, TYPE_CHECKING

from .errors import RpcError
from .protocol.methods import M, Notif
from .protocol.types import Item, TokenUsage, Turn, TurnStatus
from .session import Subscription

if TYPE_CHECKING:
    from .session import CodexSession

log = logging.getLogger(__name__)


# Callback types -- kept loose; users are expected to pass plain
# functions or async functions (we await whatever they return).

ItemCallback = Callable[[Item], Any]
NotificationCallback = Callable[[dict[str, Any]], Any]


@dataclasses.dataclass
class TurnHandle:
    """Live handle to one in-flight turn.

    Returned by :meth:`Thread.start_turn`. Has the ids you need plus a
    subscription pre-attached, ready for :func:`collect_turn`.
    """

    session: "CodexSession"
    thread_id: str
    turn_id: str
    subscription: Subscription

    async def steer(self, text: str) -> dict[str, Any]:
        """Inject a user message into this still-running turn.

        Wraps ``turn/steer`` with the ``expectedTurnId`` precondition
        the schema requires: a turn that has already rolled over will
        cleanly reject the request rather than your steer landing in
        the wrong turn.
        """
        return await self.session.request(
            M.TURN_STEER,
            {
                "threadId": self.thread_id,
                "expectedTurnId": self.turn_id,
                "input": [{"type": "text", "text": text}],
            },
        )

    async def interrupt(self) -> dict[str, Any]:
        """Cancel this turn server-side. The partial trace is preserved."""
        try:
            return await self.session.request(
                M.TURN_INTERRUPT,
                {"threadId": self.thread_id, "turnId": self.turn_id},
            )
        except RpcError as exc:
            # If the turn already finished, the server returns an error;
            # callers treat that as "interrupt succeeded by way of completion".
            log.debug("turn/interrupt rejected (likely already complete): %s", exc)
            return {}


# -----------------------------------------------------------------------
# Collect
# -----------------------------------------------------------------------

async def collect_turn(
    handle: TurnHandle,
    *,
    on_item: Optional[ItemCallback] = None,
    on_notification: Optional[NotificationCallback] = None,
    interrupt_after_items: Optional[int] = None,
    timeout: float = 300.0,
) -> Turn:
    """Drain the handle's subscription until ``turn/completed``.

    Returns a :class:`Turn`. On timeout, fires ``turn/interrupt`` and
    returns a turn with ``status="timed_out"``. Optional callbacks fire
    on every item and on every notification, respectively; exceptions
    they raise are caught and logged so they don't break the collector.

    ``interrupt_after_items`` is the headless counterpart to the IDE's
    "stop" button — handy for synthetic-data harnesses that only need
    the first N events.
    """
    items: list[Item] = []
    completion: dict[str, Any] = {}
    token_usage: Optional[TokenUsage] = None
    status: TurnStatus = "running"
    item_count = 0

    loop = asyncio.get_event_loop()
    deadline = loop.time() + timeout

    async def _maybe_await(value: Any) -> None:
        if asyncio.iscoroutine(value):
            await value

    while True:
        remaining = max(0.05, deadline - loop.time())
        try:
            ev = await asyncio.wait_for(handle.subscription.get(), timeout=remaining)
        except asyncio.TimeoutError:
            with contextlib.suppress(Exception):
                await handle.interrupt()
            status = "timed_out"
            break

        if on_notification is not None:
            try:
                await _maybe_await(on_notification(ev))
            except Exception:  # pragma: no cover
                log.exception("on_notification raised")

        method = ev.get("method", "")
        params = ev.get("params") or {}

        # Filter by thread id when present — wildcard subscriptions can
        # receive events from sibling threads in the same session.
        if "threadId" in params and params["threadId"] != handle.thread_id:
            continue

        if method == Notif.ITEM_COMPLETED:
            item = params.get("item") or params
            items.append(item)
            item_count += 1
            if on_item is not None:
                try:
                    await _maybe_await(on_item(item))
                except Exception:  # pragma: no cover
                    log.exception("on_item raised")
            if interrupt_after_items is not None and item_count >= interrupt_after_items:
                with contextlib.suppress(Exception):
                    await handle.interrupt()
        elif method == Notif.THREAD_TOKEN_USAGE_UPDATED:
            usage = params.get("tokenUsage") or {}
            total = usage.get("total")
            if isinstance(total, dict):
                token_usage = total  # type: ignore[assignment]
        elif method == Notif.TURN_COMPLETED:
            completion = params
            raw_status = (
                params.get("turn", {}).get("status")
                or params.get("status")
                or "completed"
            )
            status = raw_status  # type: ignore[assignment]
            break
        elif method == Notif.ERROR:
            completion = params
            status = "error"
            break

    return Turn(
        thread_id=handle.thread_id,
        turn_id=handle.turn_id,
        status=status,
        items=items,
        completion=completion,
        token_usage=token_usage,
    )
