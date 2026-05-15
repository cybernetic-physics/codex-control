"""GRPO-advantage math + RolloutResult value object.

Lives here for one release of grace as part of the five-package
refactor. Slated to move to ``codex_train.algorithms.grpo_advantage``
in Phase 4 (when ``codex-trainer`` is renamed to ``codex-train`` and
the rollout-runner is rewired through ``RolloutProvider``). The parallel
runner half of the old ``rollouts.py`` already moved to
:mod:`codex_orchestrate.parallel.run_rollout_group`.
"""

from __future__ import annotations

import dataclasses
from typing import Any, Iterable, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from .protocol.types import Turn


@dataclasses.dataclass(slots=True)
class RolloutResult:
    """One member of a parallel rollout group (legacy shape).

    The runner that produces these moved to
    :mod:`codex_orchestrate.parallel.run_rollout_group`; the same shape
    is duplicated there so orchestrate has no codex-control dependency
    on a value type. The two diverge in v0.2 when this module migrates
    to ``codex_train``.
    """

    member_id: str
    reward: float
    ok: bool
    elapsed_s: float
    turn: Optional[Any] = None
    verifier: Optional[Any] = None
    advantage: float = 0.0
    extra: dict[str, Any] = dataclasses.field(default_factory=dict)
    error: Optional[str] = None


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


__all__ = ["GroupStats", "RolloutResult", "grpo_advantage"]
