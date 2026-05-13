"""Smoke test: spawn the app-server, run one trivial turn, archive.

Mirrors ``experiments/app-server/01_smoke.py`` against the public API.
"""
from __future__ import annotations

import asyncio
import sys
import tempfile
from pathlib import Path

from codex_control import CodexSession, TraceWriter
from codex_control.items import summarise


async def main() -> None:
    traces = TraceWriter(Path(__file__).parent / "traces" / "01_smoke")
    with tempfile.TemporaryDirectory() as workdir:
        async with CodexSession.spawn(log_rpc_path=str(traces.rpc_log_path())) as session:
            print(f"[ok] initialized: {sorted(session.server_info.keys())}")
            thread = await session.start_thread(
                cwd=workdir, ephemeral=True, sandbox="read-only",
            )
            print(f"[ok] thread/start → {thread.thread_id}")
            turn = await thread.run_turn(
                "Reply with the single word: pong",
                cwd=workdir, approval_policy="never", effort="low", timeout=120.0,
            )
            print(f"[ok] turn status={turn.status} items={len(turn.items)}")
            for it in turn.items:
                print(f"  - {summarise(it)}")
            traces.write_turn(turn, rollout_id="smoke", extra_meta={"prompt": "pong"})
            await thread.archive()
            print("[ok] archived")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        sys.exit(130)
