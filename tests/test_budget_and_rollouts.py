"""Pure-Python unit tests for budget bookkeeping and rollout helpers."""

from __future__ import annotations

import math

from codex_control import Budget, RolloutResult, grpo_advantage
from codex_control.budget import make_token_usage_callback


def test_budget_token_update_monotonic() -> None:
    b = Budget(max_turns=4, max_tokens=1000)
    b.update_from_token_usage({"tokenUsage": {"total": {"totalTokens": 300}}})
    assert b.used_tokens == 300
    # Server resending an older total should not regress us.
    b.update_from_token_usage({"tokenUsage": {"total": {"totalTokens": 100}}})
    assert b.used_tokens == 300


def test_budget_soft_and_hard_limits() -> None:
    b = Budget(max_turns=5, max_tokens=1000)
    b.used_turns = 4  # 80%
    assert b.at_soft_limit()
    assert not b.at_hard_limit()
    b.used_turns = 5
    assert b.at_hard_limit()


def test_token_usage_callback_routes_correctly() -> None:
    b = Budget(max_turns=3, max_tokens=2000)
    cb = make_token_usage_callback(b)
    cb({"method": "thread/tokenUsage/updated",
        "params": {"tokenUsage": {"total": {"totalTokens": 700}}}})
    cb({"method": "other", "params": {"tokenUsage": {"total": {"totalTokens": 9999}}}})
    assert b.used_tokens == 700


def test_grpo_advantage_zero_mean_unit_variance() -> None:
    members = [
        RolloutResult(member_id="a", reward=1.0, ok=True, elapsed_s=0.1),
        RolloutResult(member_id="b", reward=0.0, ok=False, elapsed_s=0.1),
        RolloutResult(member_id="c", reward=1.0, ok=True, elapsed_s=0.1),
        RolloutResult(member_id="d", reward=0.0, ok=False, elapsed_s=0.1),
    ]
    stats = grpo_advantage(members)
    assert stats.size == 4
    assert math.isclose(stats.mean_reward, 0.5)
    assert math.isclose(stats.std_reward, 0.5, rel_tol=1e-6)
    # Advantages should be roughly +1 / -1.
    for m in members:
        assert math.isclose(abs(m.advantage), 1.0, abs_tol=1e-3)


def test_grpo_advantage_empty_safe() -> None:
    stats = grpo_advantage([])
    assert stats.size == 0
    assert stats.mean_reward == 0.0
