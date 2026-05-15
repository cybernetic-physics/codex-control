"""K-parallel synthetic trace generation on one app-server process.

Uses :func:`codex_orchestrate.parallel.parallel_rollouts` instead of
hand-rolled ``asyncio.gather``. Each member writes a typed JSONL trace
via :class:`codex_control.TraceWriter`.
"""
from __future__ import annotations

import asyncio
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

from codex_control import CodexSession, TraceWriter
from codex_orchestrate.parallel import RolloutResult, parallel_rollouts

DEFAULT_TASKS = [
    "Write a haiku about garbage collection. Return only the haiku.",
    "What is 17*23? Reply with just the number.",
    "List 3 hash functions used in cryptography. One per line, names only.",
    "Reverse the string 'app-server'. Reply with just the reversed string.",
]


async def one_rollout(
    session: CodexSession,
    member_id: str,
    *,
    payload: Any = None,
    traces: TraceWriter,
    **_: Any,
) -> RolloutResult:
    task = payload or "Say hi."
    t0 = time.perf_counter()
    with tempfile.TemporaryDirectory(prefix=f"syn-{member_id}-") as workdir:
        thread = await session.start_thread(
            cwd=workdir, ephemeral=True, sandbox="read-only",
        )
        turn = await thread.run_turn(
            task, cwd=workdir, approval_policy="never", effort="low", timeout=120.0,
        )
        await thread.archive()
    elapsed = time.perf_counter() - t0
    traces.write_turn(turn, rollout_id=member_id, extra_meta={"task": task, "elapsed_s": elapsed})
    return RolloutResult(
        member_id=member_id, reward=1.0 if turn.succeeded else 0.0,
        ok=turn.succeeded, elapsed_s=elapsed, turn=turn,
    )


async def main() -> None:
    k = int(sys.argv[1]) if len(sys.argv) > 1 else 4
    tasks = sys.argv[2:] or DEFAULT_TASKS
    traces = TraceWriter(Path(__file__).parent / "traces" / "02_synthetic")
    t0 = time.perf_counter()
    async with CodexSession.spawn(log_rpc_path=str(traces.rpc_log_path())) as session:
        print(f"[ok] one app-server, K={k} parallel rollouts...")
        members = await parallel_rollouts(
            session, one_rollout, k=k, payloads=tasks, prefix="r",
            traces=traces,
        )
    wall = time.perf_counter() - t0
    ok = [m for m in members if m.ok]
    err = [m for m in members if not m.ok]
    print(f"\n[ok] wall={wall:.2f}s ok={len(ok)} err={len(err)}")
    for m in members:
        snippet = (m.turn.final_text if m.turn else m.error or "")[:60]
        print(f"  {m.member_id} status={'ok' if m.ok else 'err'} elapsed={m.elapsed_s:5.2f}s  {snippet!r}")
    if ok:
        avg = sum(m.elapsed_s for m in ok) / len(ok)
        eff = avg * len(ok) / wall
        print(f"\n[stats] avg/rollout={avg:.2f}s wall={wall:.2f}s efficiency={eff:.2f}x")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        sys.exit(130)
