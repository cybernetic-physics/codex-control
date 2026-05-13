"""Fork-based tree search using :func:`codex_control.expand_all`.

Mirrors ``04_fork_tree_search.py``. Root thread must be persisted
(``ephemeral=False``) because ``thread/fork`` needs an on-disk rollout.
"""
from __future__ import annotations

import asyncio
import json
import sys
import tempfile
import time
import uuid
from pathlib import Path

from codex_control import (
    CodexSession,
    Node,
    TraceWriter,
    expand_all,
    length_value,
    select_uct,
)


ROOT_PROMPT = (
    "I am evaluating sorting algorithms for a list of 10,000 integers "
    "that's nearly already sorted. Think briefly and answer in one short paragraph."
)

BRANCH_PROMPTS = [
    "Now defend your choice against someone who insists on quicksort.",
    "Now defend your choice against someone who insists on timsort.",
    "Now argue against your own choice. What would change your mind?",
    "Now estimate the wall-clock difference vs. the naive choice on this input. One line.",
]


async def main() -> None:
    branch_factor = int(sys.argv[1]) if len(sys.argv) > 1 else len(BRANCH_PROMPTS)
    branch_factor = min(branch_factor, len(BRANCH_PROMPTS))

    traces = TraceWriter(Path(__file__).parent / "traces" / "04_fork")

    async with CodexSession.spawn(log_rpc_path=str(traces.rpc_log_path())) as session:
        with tempfile.TemporaryDirectory(prefix="fork-root-") as workdir:
            root_thread = await session.start_thread(
                cwd=workdir, ephemeral=False, sandbox="read-only",
            )
            t0 = time.perf_counter()
            root_turn = await root_thread.run_turn(
                ROOT_PROMPT, cwd=workdir, approval_policy="never", effort="low", timeout=120.0,
            )
            root = Node(
                node_id="root", thread=root_thread, parent_id=None, depth=0,
                prompt=ROOT_PROMPT, turn=root_turn, value=length_value(root_turn),
            )
            print(f"[root] thread={root_thread.thread_id[:13]} status={root_turn.status}")
            print(f"       value={root.value:.2f}  text={root_turn.final_text[:120]!r}")

            print(f"\n[branch] forking {branch_factor} children in parallel...")
            t1 = time.perf_counter()
            children = await expand_all(
                root,
                BRANCH_PROMPTS[:branch_factor],
                value_fn=length_value,
                cwd=workdir,
                approval_policy="never", effort="low", timeout=120.0,
            )
            print(f"[branch] done in {time.perf_counter()-t1:.2f}s (parent intact)")
            for c in children:
                print(
                    f"  - {c.node_id} thread={c.thread.thread_id[:13]} value={c.value:.2f}"
                )
                print(f"      → {c.final_text[:120]!r}")

            best = select_uct(children, parent_visits=root.visits)
            print(f"\n[best] {best.node_id} value={best.value:.2f}  → {best.final_text[:120]!r}")

            tree_path = traces.run_dir / f"tree_{uuid.uuid4().hex[:6]}.json"
            tree_path.write_text(json.dumps({
                "root": {"node_id": root.node_id, "thread_id": root.thread.thread_id,
                         "value": root.value, "final_text": root.final_text},
                "children": [
                    {"node_id": c.node_id, "thread_id": c.thread.thread_id,
                     "value": c.value, "prompt": c.prompt, "final_text": c.final_text}
                    for c in children
                ],
                "best": best.node_id,
                "wall_total_s": time.perf_counter() - t0,
            }, indent=2))
            print(f"\n[save] {tree_path}")

            for c in children:
                await c.thread.archive()
            await root.thread.archive()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        sys.exit(130)
