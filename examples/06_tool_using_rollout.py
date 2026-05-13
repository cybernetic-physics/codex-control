"""Tool-using rollout: produces typed ``commandExecution`` / ``fileChange`` items."""
from __future__ import annotations

import asyncio
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from codex_control import CodexSession, TraceWriter
from codex_control.items import item_type_counts, summarise


TASK_PROMPT = (
    "There is a target file at ./target.txt in your working directory. "
    "Read it, then complete the task it describes. Verify your work by "
    "running the script and showing its output. Reply 'DONE' on a line "
    "by itself when finished."
)

TARGET_TXT = """\
TASK: Create a file named hello.py containing a Python script that prints
exactly:

    hello rl world

Then run it with `python3 hello.py` and confirm the output.
"""


async def main() -> None:
    traces = TraceWriter(Path(__file__).parent / "traces" / "06_tool_using")
    with tempfile.TemporaryDirectory(prefix="tool-using-") as workdir:
        subprocess.run(["git", "init", "-q"], cwd=workdir, check=True)
        subprocess.run(
            ["git", "-c", "user.email=rl@example.com", "-c", "user.name=rl",
             "commit", "--allow-empty", "-q", "-m", "init"],
            cwd=workdir, check=True,
        )
        (Path(workdir) / "target.txt").write_text(TARGET_TXT)

        async with CodexSession.spawn(log_rpc_path=str(traces.rpc_log_path())) as session:
            thread = await session.start_thread(
                cwd=workdir, ephemeral=True,
                sandbox="workspace-write", approval_policy="never",
            )
            print(f"[ok] thread={thread.thread_id} workdir={workdir}")
            t0 = time.perf_counter()

            def on_item(it: dict) -> None:
                ts = time.perf_counter() - t0
                print(f"  +{ts:5.2f}s  {summarise(it)}")

            turn = await thread.run_turn(
                TASK_PROMPT, cwd=workdir,
                approval_policy="never", effort="low",
                timeout=240.0, on_item=on_item,
            )
            wall = time.perf_counter() - t0
            await thread.archive()

            print(f"\n[done] status={turn.status} items={len(turn.items)} wall={wall:.2f}s")
            hello = Path(workdir) / "hello.py"
            if hello.exists():
                out = subprocess.run(
                    ["python3", "hello.py"], cwd=workdir,
                    capture_output=True, text=True, timeout=10,
                ).stdout
                print(f"[verify] output={out.strip()!r} → "
                      f"{'PASS' if out.strip() == 'hello rl world' else 'FAIL'}")
            else:
                print("[verify] hello.py not created → FAIL")
            print(f"[counts] {item_type_counts(turn.items)}")
            traces.write_turn(turn, rollout_id="tool", extra_meta={"workdir": workdir})


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        sys.exit(130)
