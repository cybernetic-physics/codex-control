"""K-parallel rollouts over one remote WS — proves the WS path is a drop-in."""
from __future__ import annotations

import asyncio
import os
import sys
import time
from pathlib import Path
from typing import Any

from codex_control import CodexSession, TraceWriter
from codex_orchestrate.parallel import RolloutResult, parallel_rollouts


TASKS = [
    "What is 17*23? Reply with just the number.",
    "Reverse the string 'remote'. Reply with just the reversed string.",
    "Reply with exactly three words about the color blue.",
    "What is 2 to the power of 16? Reply with just the number.",
]


async def one_rollout(
    session: CodexSession,
    member_id: str,
    *,
    payload: Any = None,
    **_: Any,
) -> RolloutResult:
    task = payload or "Say hi."
    t0 = time.perf_counter()
    thread = await session.start_thread(
        cwd="/tmp", ephemeral=True, sandbox="read-only",
        approval_policy="never",
    )
    try:
        turn = await thread.run_turn(
            task, approval_policy="never", effort="low", timeout=120.0,
        )
    finally:
        await thread.archive()
    elapsed = time.perf_counter() - t0
    return RolloutResult(
        member_id=member_id,
        reward=1.0 if turn.succeeded else 0.0,
        ok=turn.succeeded,
        elapsed_s=elapsed,
        turn=turn,
    )


async def main() -> None:
    url = os.environ.get("REMOTE_URL", "ws://codex-server:8765")
    token = os.environ.get("WS_TOKEN")
    k = int(os.environ.get("K", "4"))
    if not token:
        print("ERR: WS_TOKEN env var required", file=sys.stderr)
        sys.exit(2)

    traces = TraceWriter(Path(__file__).parent.parent / "traces" / "remote_15")
    print(f"[client] connecting to {url}, K={k}")
    async with CodexSession.connect(
        url, token=token, log_rpc_path=str(traces.rpc_log_path()),
    ) as session:
        t0 = time.perf_counter()
        members = await parallel_rollouts(
            session, one_rollout, k=k, payloads=TASKS, prefix="r",
        )
        wall = time.perf_counter() - t0

    ok = [m for m in members if m.ok]
    err = [m for m in members if not m.ok]
    print(f"\n[client] wall={wall:.2f}s ok={len(ok)} err={len(err)}")
    for m in members:
        snippet = (m.turn.final_text if m.turn else m.error or "")[:60]
        print(f"  {m.member_id} status={'ok' if m.ok else 'err'} t={m.elapsed_s:5.2f}s → {snippet!r}")
    if ok:
        avg = sum(m.elapsed_s for m in ok) / len(ok)
        print(f"[stats] avg={avg:.2f}s wall={wall:.2f}s efficiency={avg*len(ok)/wall:.2f}x")


if __name__ == "__main__":
    asyncio.run(main())
