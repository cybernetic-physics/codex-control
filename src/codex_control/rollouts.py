"""Deprecated. The parallel-rollout *runner* moved to
:mod:`codex_orchestrate.parallel.run_rollout_group`; the GRPO-advantage
*math* (this file's :func:`grpo_advantage` and :class:`GroupStats`) is
slated for :mod:`codex_train.algorithms` in Phase 4. Until then it stays
here so existing callers don't break.

Importers that were doing ``from codex_control import parallel_rollouts``
or ``from codex_control import single_turn_group`` should switch to
``from codex_orchestrate.parallel import parallel_rollouts``. The
``RolloutResult`` / ``GroupStats`` / ``grpo_advantage`` exports remain
available from this module for one release of grace; they will move to
``codex_train.algorithms`` in v0.2.
"""

from __future__ import annotations

import dataclasses
from typing import Any, Iterable, Optional

# Re-export the value object + math from the local legacy stash.
from ._legacy_advantage import (
    GroupStats,
    RolloutResult,
    grpo_advantage,
)

__all__ = [
    "GroupStats",
    "RolloutResult",
    "grpo_advantage",
]
