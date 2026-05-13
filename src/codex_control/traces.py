"""Trace writers.

Two formats, one writer:

* JSON lines (``write_turn_jsonl``): one ``_meta`` row followed by one
  row per item. Matches the format used in
  ``traces/02_synthetic/*.jsonl``. Best for streaming / appendable
  trace collection.

* Structured JSON (``write_group_json``): one file per group/episode.
  Matches ``traces/03_grpo/group_*.json`` and ``traces/09_rlvr/episode.json``.
  Best for offline analysis.

:class:`TraceWriter` is a thin convenience class that owns an output
directory and gives you per-rollout/per-group/per-episode helpers. Use
the bare functions if you'd rather manage paths yourself.
"""

from __future__ import annotations

import dataclasses
import json
import logging
import os
import time
import uuid
from pathlib import Path
from typing import Any, Iterable, Optional

from .protocol.types import Turn
from .rollouts import GroupStats, RolloutResult

log = logging.getLogger(__name__)


# -----------------------------------------------------------------------
# Free-standing writers
# -----------------------------------------------------------------------

def write_turn_jsonl(
    path: Path | str,
    turn: Turn,
    *,
    extra_meta: Optional[dict[str, Any]] = None,
) -> Path:
    """Write one turn to ``path`` as JSONL.

    Layout: a single ``{"_meta": {...}}`` row, then one row per item.
    """
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    meta: dict[str, Any] = {
        "thread_id": turn.thread_id,
        "turn_id": turn.turn_id,
        "status": turn.status,
        "num_items": len(turn.items),
        "token_usage": dict(turn.token_usage or {}),
    }
    if extra_meta:
        meta.update(extra_meta)
    with p.open("w", encoding="utf-8") as f:
        f.write(json.dumps({"_meta": meta}) + "\n")
        for item in turn.items:
            f.write(json.dumps(item) + "\n")
    return p


def write_group_json(
    path: Path | str,
    *,
    members: Iterable[RolloutResult],
    stats: Optional[GroupStats] = None,
    metadata: Optional[dict[str, Any]] = None,
) -> Path:
    """Write a full group rollout (GRPO etc.) to a single JSON file."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    payload: dict[str, Any] = {
        "members": [_rollout_to_dict(m) for m in members],
        "stats": dataclasses.asdict(stats) if stats is not None else None,
        "metadata": metadata or {},
    }
    p.write_text(json.dumps(payload, indent=2, default=str))
    return p


def _rollout_to_dict(m: RolloutResult) -> dict[str, Any]:
    return {
        "member_id": m.member_id,
        "reward": m.reward,
        "ok": m.ok,
        "advantage": m.advantage,
        "elapsed_s": m.elapsed_s,
        "error": m.error,
        "turn": _turn_to_dict(m.turn) if m.turn is not None else None,
        "verifier": dataclasses.asdict(m.verifier) if m.verifier is not None else None,
        "extra": m.extra,
    }


def _turn_to_dict(t: Turn) -> dict[str, Any]:
    return {
        "thread_id": t.thread_id,
        "turn_id": t.turn_id,
        "status": t.status,
        "items": t.items,
        "token_usage": dict(t.token_usage or {}),
    }


# -----------------------------------------------------------------------
# TraceWriter
# -----------------------------------------------------------------------

class TraceWriter:
    """Convenience writer owning an output directory.

    Layout::

        <root>/<run_id>/
            rollouts/<rollout_id>.jsonl       # per-turn JSONL
            groups/<group_id>.json            # per-group summary
            episodes/<episode_id>.json        # per-episode summary

    ``run_id`` defaults to a short uuid + timestamp so concurrent runs
    don't stomp each other.
    """

    def __init__(
        self,
        root: Path | str,
        *,
        run_id: Optional[str] = None,
    ) -> None:
        self.root = Path(root)
        self.run_id = run_id or self._make_run_id()
        self.run_dir = self.root / self.run_id
        self.rollouts_dir = self.run_dir / "rollouts"
        self.groups_dir = self.run_dir / "groups"
        self.episodes_dir = self.run_dir / "episodes"
        for d in (self.rollouts_dir, self.groups_dir, self.episodes_dir):
            d.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _make_run_id() -> str:
        return f"{time.strftime('%Y%m%dT%H%M%S')}-{uuid.uuid4().hex[:6]}"

    def rpc_log_path(self) -> Path:
        return self.run_dir / "_rpc.jsonl"

    def turn_path(self, rollout_id: Optional[str] = None) -> Path:
        rid = rollout_id or f"r-{uuid.uuid4().hex[:6]}"
        return self.rollouts_dir / f"{rid}.jsonl"

    def write_turn(
        self, turn: Turn, *, rollout_id: Optional[str] = None, extra_meta: Optional[dict[str, Any]] = None
    ) -> Path:
        return write_turn_jsonl(
            self.turn_path(rollout_id), turn, extra_meta=extra_meta
        )

    def write_group(
        self,
        members: Iterable[RolloutResult],
        *,
        stats: Optional[GroupStats] = None,
        metadata: Optional[dict[str, Any]] = None,
        group_id: Optional[str] = None,
    ) -> Path:
        gid = group_id or f"g-{uuid.uuid4().hex[:6]}"
        return write_group_json(
            self.groups_dir / f"{gid}.json",
            members=members, stats=stats, metadata=metadata,
        )

    def write_episode(
        self,
        episode: Any,
        *,
        episode_id: Optional[str] = None,
    ) -> Path:
        """Persist any dataclass / dict episode payload as JSON."""
        eid = episode_id or f"ep-{uuid.uuid4().hex[:6]}"
        p = self.episodes_dir / f"{eid}.json"
        payload = (
            dataclasses.asdict(episode)
            if dataclasses.is_dataclass(episode)
            else episode
        )
        p.write_text(json.dumps(payload, indent=2, default=str))
        return p
