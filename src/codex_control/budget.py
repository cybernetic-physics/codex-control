"""Budget bookkeeping and soft-limit steering.

The :class:`Budget` dataclass tracks ``(turns_used, tokens_used)`` against
caps. Two practical helpers come with it:

* :func:`update_from_token_usage` — feed a ``thread/tokenUsage/updated``
  notification into a budget. The wire key is exactly
  ``thread/tokenUsage/updated`` (with the slash before ``updated``); the
  payload is ``{total, last, modelContextWindow}`` where ``total`` is
  cumulative.

* :class:`BudgetSteerWatcher` — async helper that fires ``turn/steer``
  when either dimension crosses a soft threshold (default 0.8). This is
  the headless equivalent of the IDE's "are you sure" nudge.

Hard-limit enforcement (interrupt the turn outright) is left to the
caller; usually you want the soft-limit steer first, then a hard cap on
the *next* turn.
"""

from __future__ import annotations

import asyncio
import contextlib
import dataclasses
import logging
from typing import Any, Optional, TYPE_CHECKING

from .protocol.methods import Notif
from .protocol.types import TokenUsage

if TYPE_CHECKING:
    from .turn import TurnHandle

log = logging.getLogger(__name__)


@dataclasses.dataclass
class Budget:
    """Mutable per-episode budget tracker.

    Tokens are cumulative from ``thread/tokenUsage/updated.total.totalTokens``.
    Turns are caller-incremented (the budget can't tell you how many
    user turns you've sent without help; call :meth:`bump_turn` before
    each ``turn/start``).
    """

    max_turns: int
    max_tokens: int
    used_turns: int = 0
    used_tokens: int = 0
    last_token_usage: TokenUsage = dataclasses.field(default_factory=dict)  # type: ignore[arg-type]
    soft_threshold: float = 0.8
    soft_steered: bool = False

    # --- queries ------------------------------------------------------

    @property
    def turn_pct(self) -> float:
        return self.used_turns / max(1, self.max_turns)

    @property
    def token_pct(self) -> float:
        return self.used_tokens / max(1, self.max_tokens)

    def at_soft_limit(self) -> bool:
        return (
            self.turn_pct >= self.soft_threshold
            or self.token_pct >= self.soft_threshold
        )

    def at_hard_limit(self) -> bool:
        return (
            self.used_turns >= self.max_turns
            or self.used_tokens >= self.max_tokens
        )

    # --- mutators -----------------------------------------------------

    def bump_turn(self) -> None:
        self.used_turns += 1
        self.soft_steered = False

    def update_from_token_usage(self, payload: dict[str, Any]) -> None:
        """Apply one ``thread/tokenUsage/updated`` notification.

        ``payload`` is the notification's ``params`` dict; the relevant
        nested shape is ``{"tokenUsage": {"total": {...}, "last": {...}, ...}}``.
        Monotonic: ``used_tokens`` only increases.
        """
        usage = payload.get("tokenUsage") or {}
        total = usage.get("total")
        if isinstance(total, dict):
            self.last_token_usage = total  # type: ignore[assignment]
            self.used_tokens = max(
                self.used_tokens, int(total.get("totalTokens", 0))
            )

    # --- diagnostics --------------------------------------------------

    def snapshot(self) -> dict[str, Any]:
        return {
            "max_turns": self.max_turns,
            "max_tokens": self.max_tokens,
            "used_turns": self.used_turns,
            "used_tokens": self.used_tokens,
            "turn_pct": self.turn_pct,
            "token_pct": self.token_pct,
            "soft_steered": self.soft_steered,
            "last_token_usage": dict(self.last_token_usage or {}),
        }


# -----------------------------------------------------------------------
# Steer watcher
# -----------------------------------------------------------------------

DEFAULT_STEER_PROMPT = (
    "BUDGET ALERT: you have less than 20% of your turn/token budget left. "
    "Stop exploring — make your best final fix in this turn and reply DONE."
)


class BudgetSteerWatcher:
    """Background helper that fires :meth:`TurnHandle.steer` on soft-limit.

    Run as ``async with watcher:`` while the turn is in progress; the
    watcher cancels itself on context exit. It will fire ``turn/steer``
    at most once per turn (using ``Budget.soft_steered``).
    """

    def __init__(
        self,
        handle: "TurnHandle",
        budget: Budget,
        *,
        steer_prompt: str = DEFAULT_STEER_PROMPT,
        poll_interval: float = 0.5,
    ) -> None:
        self._handle = handle
        self._budget = budget
        self._steer_prompt = steer_prompt
        self._poll_interval = poll_interval
        self._task: Optional[asyncio.Task[None]] = None

    async def __aenter__(self) -> "BudgetSteerWatcher":
        self._task = asyncio.create_task(self._run())
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await self._task

    async def _run(self) -> None:
        while True:
            await asyncio.sleep(self._poll_interval)
            if self._budget.soft_steered:
                return
            if not self._budget.at_soft_limit():
                continue
            self._budget.soft_steered = True
            log.info(
                "BudgetSteerWatcher firing turn/steer "
                "(turns=%d/%d tokens=%d/%d)",
                self._budget.used_turns, self._budget.max_turns,
                self._budget.used_tokens, self._budget.max_tokens,
            )
            try:
                await self._handle.steer(self._steer_prompt)
            except Exception as exc:  # pragma: no cover
                log.debug("steer rejected (turn likely complete): %s", exc)
            return


# -----------------------------------------------------------------------
# Notification callback factory
# -----------------------------------------------------------------------

def make_token_usage_callback(budget: Budget):
    """Return a notification callback that feeds token-usage into ``budget``.

    Pair with :func:`collect_turn(on_notification=...) <codex_control.turn.collect_turn>`
    to update the budget live as the turn progresses.
    """

    def _cb(ev: dict[str, Any]) -> None:
        if ev.get("method") == Notif.THREAD_TOKEN_USAGE_UPDATED:
            budget.update_from_token_usage(ev.get("params") or {})

    return _cb
