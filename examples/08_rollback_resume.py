"""``thread/rollback`` ablation: drop last N turns, re-ask, verify pruning."""
from __future__ import annotations

import asyncio
import json
import sys
import tempfile
from pathlib import Path

from codex_control import CodexSession, TraceWriter
from codex_control.items import last_agent_message


async def main() -> None:
    traces = TraceWriter(Path(__file__).parent / "traces" / "08_rollback")
    async with CodexSession.spawn(log_rpc_path=str(traces.rpc_log_path())) as session:
        with tempfile.TemporaryDirectory(prefix="rollback-") as workdir:
            thread = await session.start_thread(
                cwd=workdir, ephemeral=False, sandbox="read-only",
            )
            print(f"[ok] thread={thread.thread_id}")

            t1 = await thread.run_turn(
                "I have a list of 1 million names that I need to deduplicate. "
                "Suggest the simplest one-line approach in Python. One short line.",
                cwd=workdir, approval_policy="never", effort="low", timeout=120.0,
            )
            print(f"[t1] {last_agent_message(t1.items)[:100]!r}")

            t2 = await thread.run_turn(
                "Now rewrite the same solution using bubble-sort first to "
                "remove duplicates. One short paragraph.",
                cwd=workdir, approval_policy="never", effort="low", timeout=120.0,
            )
            print(f"[t2] {last_agent_message(t2.items)[:100]!r}")

            t3 = await thread.run_turn(
                "Also rewrite it in COBOL. One short snippet.",
                cwd=workdir, approval_policy="never", effort="low", timeout=120.0,
            )
            print(f"[t3] {last_agent_message(t3.items)[:100]!r}")

            print("\n[rollback] dropping last 2 turns...")
            rb = await thread.rollback(num_turns=2)
            kept = (rb.get("thread") or {}).get("turns") or []
            print(f"[rollback] kept {len(kept)} turns")

            t4 = await thread.run_turn(
                "Out of everything you suggested so far, which is the most "
                "Pythonic option? Reply in one short sentence.",
                cwd=workdir, approval_policy="never", effort="low", timeout=120.0,
            )
            final = last_agent_message(t4.items)
            print(f"\n[t4 after rollback] {final[:200]!r}")
            mentions = {
                "bubble": "bubble" in final.lower(),
                "cobol": "cobol" in final.lower(),
            }
            print(
                f"[verify] mentions: {mentions} → "
                f"{'CONTEXT_PRUNED' if not any(mentions.values()) else 'CONTEXT_LEAKED'}"
            )
            (traces.run_dir / "summary.json").write_text(json.dumps({
                "t4": final, "mentions": mentions,
            }, indent=2))
            await thread.archive()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        sys.exit(130)
