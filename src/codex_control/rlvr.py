"""RLVR (RL with Verifiable Reward) multi-turn loop.

Generalises ``09_rlvr_budget_eval.py`` into a reusable function:

* one persistent thread per episode (so token-usage notifications make
  sense),
* a configurable :class:`~codex_control.verifiers.Verifier` at the end
  (and optionally between turns),
* a :class:`~codex_control.budget.Budget` with soft-limit steering via
  :class:`~codex_control.budget.BudgetSteerWatcher`,
* a caller-supplied follow-up prompt builder so the protocol of "what
  do I tell the agent on retry" stays with the task author.

Reward shaping is left to the caller — they can use the verifier's raw
``reward`` or post-process with :func:`shape_rlvr_reward` for the
length-penalty pattern from the experiment.
"""

from __future__ import annotations

import asyncio
import dataclasses
import logging
import time
from typing import Any, Awaitable, Callable, Optional, TYPE_CHECKING

from .budget import Budget, BudgetSteerWatcher, make_token_usage_callback
from .errors import RpcError
from .items import last_agent_message
from .protocol.types import Turn
from .turn import collect_turn
from .verifiers import Verifier, VerifierResult

if TYPE_CHECKING:
    from .thread import Thread

log = logging.getLogger(__name__)


# A follow-up builder receives ``(turn, verifier_result, context)`` and
# returns the prompt to send on the next turn (or ``None`` to stop).
FollowupBuilder = Callable[[Turn, VerifierResult, dict[str, Any]], Optional[str]]


@dataclasses.dataclass
class RlvrEpisode:
    """Outcome of one RLVR episode."""

    thread_id: str
    turns: list[Turn]
    verifier_results: list[VerifierResult]
    final_verifier: VerifierResult
    budget: dict[str, Any]
    reward: float
    reward_breakdown: dict[str, Any]
    elapsed_s: float


# -----------------------------------------------------------------------
# Reward shaping helper
# -----------------------------------------------------------------------

def shape_rlvr_reward(
    final: VerifierResult,
    *,
    budget: Budget,
    length_penalty_per_extra_turn: float = 0.05,
) -> tuple[float, dict[str, Any]]:
    """Apply the canonical RLVR shaping from the experiments:

    ``reward = max(0, partial - length_penalty)``

    where ``partial`` is the verifier's reward (so partial credit during
    multi-turn debugging counts) and ``length_penalty`` discourages
    running the budget out.
    """
    terminal = 1.0 if final.ok else 0.0
    partial = final.reward
    length_penalty = length_penalty_per_extra_turn * max(0, budget.used_turns - 1)
    reward = max(0.0, partial - length_penalty)
    return reward, {
        "terminal_reward": terminal,
        "partial": partial,
        "length_penalty": length_penalty,
        "raw": dataclasses.asdict(final),
    }


# -----------------------------------------------------------------------
# Main loop
# -----------------------------------------------------------------------

async def run_rlvr_episode(
    thread: "Thread",
    initial_prompt: str,
    *,
    verifier: Verifier,
    budget: Budget,
    followup_builder: FollowupBuilder,
    cwd: Optional[str] = None,
    approval_policy: str = "never",
    effort: str = "low",
    steer_on_soft_limit: bool = True,
    steer_prompt: Optional[str] = None,
    per_turn_timeout: float = 240.0,
    context: Optional[dict[str, Any]] = None,
    shape_reward: bool = True,
) -> RlvrEpisode:
    """Run a multi-turn RLVR episode against ``thread`` until success or budget.

    The loop terminates when:

    * The verifier returns ``ok=True`` (success), or
    * ``budget.at_hard_limit()`` (cap hit), or
    * ``followup_builder`` returns ``None`` (caller declined to retry).
    """
    ctx = dict(context or {})
    ep_t0 = time.perf_counter()
    turns: list[Turn] = []
    verdicts: list[VerifierResult] = []
    prompt = initial_prompt
    final_verdict: Optional[VerifierResult] = None

    while not budget.at_hard_limit():
        budget.bump_turn()
        log.info(
            "rlvr turn %d/%d (tokens %d/%d)",
            budget.used_turns, budget.max_turns,
            budget.used_tokens, budget.max_tokens,
        )

        handle = await thread.start_turn(
            prompt,
            cwd=cwd,
            approval_policy=approval_policy,
            effort=effort,
        )
        on_notif = make_token_usage_callback(budget)
        async with handle.subscription:
            collector = asyncio.create_task(
                collect_turn(
                    handle,
                    on_notification=on_notif,
                    timeout=per_turn_timeout,
                )
            )
            if steer_on_soft_limit:
                async with BudgetSteerWatcher(
                    handle, budget,
                    steer_prompt=steer_prompt
                    or "BUDGET ALERT: less than 20% of your budget remains; finalise now.",
                ):
                    turn = await collector
            else:
                turn = await collector

        turns.append(turn)
        verdict = verifier(turn, **ctx)
        verdicts.append(verdict)
        log.info(
            "rlvr verifier: reward=%.3f ok=%s reason=%s",
            verdict.reward, verdict.ok, verdict.reason,
        )

        if verdict.ok:
            final_verdict = verdict
            break
        if budget.at_hard_limit():
            final_verdict = verdict
            break

        followup = followup_builder(turn, verdict, ctx)
        if followup is None:
            final_verdict = verdict
            break
        prompt = followup

    # If we somehow exited without setting final, use the last verdict.
    if final_verdict is None:
        final_verdict = verdicts[-1] if verdicts else VerifierResult(
            reward=0.0, ok=False, reason="no verdicts"
        )

    if shape_reward:
        reward, breakdown = shape_rlvr_reward(final_verdict, budget=budget)
    else:
        reward, breakdown = final_verdict.reward, {"raw": dataclasses.asdict(final_verdict)}

    return RlvrEpisode(
        thread_id=thread.thread_id,
        turns=turns,
        verifier_results=verdicts,
        final_verifier=final_verdict,
        budget=budget.snapshot(),
        reward=reward,
        reward_breakdown=breakdown,
        elapsed_s=time.perf_counter() - ep_t0,
    )


# -----------------------------------------------------------------------
# Default follow-up builders
# -----------------------------------------------------------------------

def pytest_followup(
    turn: Turn,
    verdict: VerifierResult,
    context: dict[str, Any],
) -> Optional[str]:
    """Default follow-up that pastes the pytest output back at the agent.

    Use with :class:`~codex_control.verifiers.PytestVerifier`.
    """
    info = verdict.info or {}
    passed = info.get("passed", 0)
    failed = info.get("failed", 0)
    stdout = info.get("stdout_tail", "")[-500:]
    return (
        f"Tests are still failing ({failed} fail, {passed} pass). pytest output:\n"
        f"```\n{stdout}\n```\n"
        f"Continue fixing. Reply 'DONE' on a single line when all tests pass."
    )


def regex_followup(
    turn: Turn,
    verdict: VerifierResult,
    context: dict[str, Any],
) -> Optional[str]:
    """Default follow-up for a :class:`~codex_control.verifiers.RegexVerifier`."""
    final = last_agent_message(turn.items)
    expected = context.get("expected", "the required pattern")
    return (
        f"Your answer was {final[:80]!r} which didn't match {expected!r}. "
        f"Try again, and respond with the exact required form."
    )
