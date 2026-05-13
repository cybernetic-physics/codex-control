"""TraceWriter behaviour."""

from __future__ import annotations

import json
from pathlib import Path

from codex_control import (
    GroupStats,
    RolloutResult,
    TraceWriter,
    Turn,
)


def test_write_turn_jsonl(tmp_path: Path) -> None:
    tw = TraceWriter(tmp_path, run_id="run1")
    turn = Turn(
        thread_id="T", turn_id="U", status="completed",
        items=[{"type": "agentMessage", "text": "ok"}],
    )
    p = tw.write_turn(turn, rollout_id="r1", extra_meta={"task": "x"})
    assert p.exists()
    lines = p.read_text().splitlines()
    meta = json.loads(lines[0])["_meta"]
    assert meta["thread_id"] == "T" and meta["task"] == "x"
    assert json.loads(lines[1])["text"] == "ok"


def test_write_group_json(tmp_path: Path) -> None:
    tw = TraceWriter(tmp_path, run_id="run2")
    members = [
        RolloutResult(member_id="a", reward=1.0, ok=True, elapsed_s=0.1, advantage=1.0),
        RolloutResult(member_id="b", reward=0.0, ok=False, elapsed_s=0.1, advantage=-1.0),
    ]
    stats = GroupStats(size=2, mean_reward=0.5, std_reward=0.5, min_reward=0.0, max_reward=1.0)
    p = tw.write_group(members, stats=stats, metadata={"prompt": "x"}, group_id="g1")
    payload = json.loads(p.read_text())
    assert payload["stats"]["mean_reward"] == 0.5
    assert payload["metadata"]["prompt"] == "x"
    assert {m["member_id"] for m in payload["members"]} == {"a", "b"}


def test_runs_isolated(tmp_path: Path) -> None:
    a = TraceWriter(tmp_path, run_id="a")
    b = TraceWriter(tmp_path, run_id="b")
    assert a.run_dir != b.run_dir
    assert a.rpc_log_path() != b.rpc_log_path()
