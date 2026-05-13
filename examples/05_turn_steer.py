"""``turn/steer`` mid-rollout adversarial-user injection.

Demonstrates :meth:`TurnHandle.steer`. The flow uses
``thread.start_turn`` (not ``run_turn``) so we hold a handle and can
race the steer against the collector.
"""
from __future__ import annotations

import asyncio
import json
import sys
import tempfile
import time
from pathlib import Path

from codex_control import CodexSession, TraceWriter, collect_turn


INITIAL_PROMPT = (
    "Write a 400-word reflective essay on why static typing matters in "
    "large Python codebases. Use concrete examples. Take your time and "
    "write it out fully."
)
STEER_AFTER_S = 6.0
STEER_PROMPT = (
    "STOP. I changed my mind — drop the essay entirely and instead just "
    "list five popular Python static type checkers, one per line, names only. "
    "Do not continue the essay."
)


async def main() -> None:
    traces = TraceWriter(Path(__file__).parent / "traces" / "05_steer")
    async with CodexSession.spawn(log_rpc_path=str(traces.rpc_log_path())) as session:
        with tempfile.TemporaryDirectory(prefix="steer-") as workdir:
            thread = await session.start_thread(
                cwd=workdir, ephemeral=True, sandbox="read-only",
            )
            print(f"[ok] thread={thread.thread_id}")

            timeline: list[dict] = []
            t0 = time.perf_counter()

            def record(item: dict) -> None:
                kind = item.get("type")
                snippet = (item.get("text") or json.dumps(item))[:120]
                ts = time.perf_counter() - t0
                timeline.append({"t": ts, "type": kind, "snippet": snippet})
                print(f"  +{ts:5.2f}s  {kind:14}  {snippet!r}")

            handle = await thread.start_turn(
                INITIAL_PROMPT, cwd=workdir,
                approval_policy="never", effort="low",
            )
            print(f"[ok] turn_id={handle.turn_id}  steer after {STEER_AFTER_S}s")
            async with handle.subscription:
                collector = asyncio.create_task(
                    collect_turn(handle, on_item=record, timeout=180.0)
                )
                deadline = t0 + STEER_AFTER_S
                while not collector.done():
                    remaining = deadline - time.perf_counter()
                    if remaining <= 0:
                        break
                    try:
                        await asyncio.wait_for(asyncio.shield(collector), timeout=remaining)
                        break
                    except asyncio.TimeoutError:
                        break

                if collector.done():
                    print("[note] turn finished before steer fired.")
                else:
                    print(f"\n[steer] firing turn/steer at +{time.perf_counter()-t0:.2f}s")
                    try:
                        await handle.steer(STEER_PROMPT)
                    except Exception as exc:
                        print(f"[steer] rejected: {exc}")
                turn = await collector

            print(
                f"\n[done] status={turn.status} items={len(turn.items)} "
                f"wall={time.perf_counter()-t0:.2f}s"
            )
            traces.write_turn(turn, rollout_id="steer", extra_meta={"timeline": timeline})
            await thread.archive()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        sys.exit(130)
