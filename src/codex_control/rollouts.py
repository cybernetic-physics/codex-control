"""Group sampling, parallel rollouts, and GRPO advantage.

These primitives correspond directly to the experiment scripts:
``02_synthetic_traces.py`` (K-parallel offline data) and
``03_grpo_group_sample.py`` (group sampling + advantage).

The shape is composable: a *rollout function* is any async callable that
takes ``(session, member_id, **kwargs)`` and returns a
:class:`RolloutResult`. The library doesn't prescribe what your rollout
does — set up a workspace, run one or many turns, attach a verifier —
it just runs ``K`` of them in parallel on the same session and gives
you back the results plus computed advantages.
"""

from __future__ import annotations

import asyncio
import dataclasses
import logging
import time
import uuid
from typing import Any, Awaitable, Callable, Iterable, Optional, Sequence, TYPE_CHECKING

from .protocol.types import Turn
from .verifiers import VerifierResult

if TYPE_CHECKING:
    from .session import CodexSession

log = logging.getLogger(__name__)


@dataclasses.dataclass(slots=True)
class RolloutResult:
    """One member of a parallel rollout group.

    ``turn`` is optional because some rollouts span multiple turns and
    only carry the final one; ``extra`` is the escape hatch for anything
    the rollout function wants to attach (per-step traces, side effects,
    etc.).
    """

    member_id: str
    reward: float
    ok: bool
    elapsed_s: float
    turn: Optional[Turn] = None
    verifier: Optional[VerifierResult] = None
    advantage: float = 0.0
    extra: dict[str, Any] = dataclasses.field(default_factory=dict)
    error: Optional[str] = None


# A rollout function signature. Returns a RolloutResult (sync-typed for
# Protocol simplicity, but always async-called).
RolloutFn = Callable[..., Awaitable[RolloutResult]]


# -----------------------------------------------------------------------
# Parallel runner
# -----------------------------------------------------------------------

async def parallel_rollouts(
    session: "CodexSession",
    rollout_fn: RolloutFn,
    *,
    k: int,
    payloads: Optional[Sequence[Any]] = None,
    prefix: str = "r",
    return_exceptions: bool = True,
    **shared_kwargs: Any,
) -> list[RolloutResult]:
    """Run ``k`` independent rollouts concurrently on one session.

    The rollout function is called with ``(session, member_id, payload=...,
    **shared_kwargs)``. If ``payloads`` is shorter than ``k``, it cycles.
    If ``payloads`` is ``None``, ``payload=None`` is passed every time.

    Exceptions from individual rollouts are captured as
    :class:`RolloutResult` with ``ok=False`` and ``error=...`` (so a
    single failure doesn't drag the whole batch down). Set
    ``return_exceptions=False`` to surface exceptions raw.
    """
    if k <= 0:
        return []
    plan: list[Any] = (
        [payloads[i % len(payloads)] for i in range(k)]
        if payloads
        else [None] * k
    )

    async def _one(i: int, payload: Any) -> RolloutResult:
        member_id = f"{prefix}{i:02d}-{uuid.uuid4().hex[:6]}"
        try:
            return await rollout_fn(
                session, member_id, payload=payload, **shared_kwargs
            )
        except Exception as exc:
            log.exception("rollout %s raised", member_id)
            if not return_exceptions:
                raise
            return RolloutResult(
                member_id=member_id,
                reward=0.0,
                ok=False,
                elapsed_s=0.0,
                error=f"{type(exc).__name__}: {exc}",
            )

    return await asyncio.gather(
        *(_one(i, plan[i]) for i in range(k)), return_exceptions=False
    )


# -----------------------------------------------------------------------
# GRPO advantage
# -----------------------------------------------------------------------

@dataclasses.dataclass(slots=True)
class GroupStats:
    """Summary statistics over a group of rollouts."""

    size: int
    mean_reward: float
    std_reward: float
    min_reward: float
    max_reward: float


def grpo_advantage(
    members: Iterable[RolloutResult],
    *,
    eps: float = 1e-6,
    in_place: bool = True,
) -> GroupStats:
    """Compute per-member GRPO advantages and overwrite ``.advantage`` on each.

    The classic GRPO formula:

    .. math::

        a_i = \\frac{r_i - \\bar{r}}{\\sigma_r + \\epsilon}

    Returns summary statistics over the group. With ``in_place=False``
    the members are not mutated — useful for analysis.
    """
    rewards = [m.reward for m in members]
    n = len(rewards)
    if n == 0:
        return GroupStats(0, 0.0, 0.0, 0.0, 0.0)
    mean = sum(rewards) / n
    var = sum((r - mean) ** 2 for r in rewards) / n
    std = var ** 0.5
    if in_place:
        for m, r in zip(members, rewards):
            m.advantage = (r - mean) / (std + eps)
    return GroupStats(
        size=n,
        mean_reward=mean,
        std_reward=std,
        min_reward=min(rewards),
        max_reward=max(rewards),
    )


# -----------------------------------------------------------------------
# Convenience: single-turn group sampler
# -----------------------------------------------------------------------

async def single_turn_group(
    session: "CodexSession",
    *,
    prompt: str,
    verifier: Callable[[Turn], VerifierResult],
    k: int = 4,
    cwd: Optional[str] = None,
    sandbox: str = "read-only",
    approval_policy: str = "never",
    effort: str = "low",
    timeout: float = 120.0,
    prefix: str = "g",
) -> tuple[list[RolloutResult], GroupStats]:
    """Run K single-turn rollouts of the same prompt and compute advantages.

    Each member uses an ephemeral thread and the supplied verifier. This
    is the bare-bones GRPO group used in ``03_grpo_group_sample.py``,
    factored as a reusable function.
    """

    async def _member(
        session: "CodexSession",
        member_id: str,
        *,
        payload: Any = None,
        **_: Any,
    ) -> RolloutResult:
        t0 = time.perf_counter()
        thread = await session.start_thread(
            cwd=cwd, ephemeral=True, sandbox=sandbox,
            approval_policy=approval_policy,
        )
        try:
            turn = await thread.run_turn(
                prompt,
                cwd=cwd,
                approval_policy=approval_policy,
                effort=effort,
                timeout=timeout,
            )
        finally:
            await thread.archive()
        elapsed = time.perf_counter() - t0
        vr = verifier(turn)
        return RolloutResult(
            member_id=member_id,
            reward=vr.reward,
            ok=vr.ok,
            elapsed_s=elapsed,
            turn=turn,
            verifier=vr,
        )

    members = await parallel_rollouts(
        session, _member, k=k, prefix=prefix,
    )
    stats = grpo_advantage(members)
    return members, stats
