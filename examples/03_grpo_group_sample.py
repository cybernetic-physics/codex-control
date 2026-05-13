"""GRPO group sampling + per-group advantage computation.

Demonstrates :func:`single_turn_group` plus :class:`RegexVerifier`. Env
passthrough (``OPENAI_BASE_URL``) reaches the app-server child via
``CodexSession.spawn(env=...)``.
"""
from __future__ import annotations

import asyncio
import os
import sys
import time
from pathlib import Path

from codex_control import (
    CodexSession,
    RegexVerifier,
    TraceWriter,
    single_turn_group,
)


TASKS = [
    ("What is 17*23? Reply with just the number.", r"\b391\b"),
    ("Compute 1+2+3+...+100. Reply with only the number.", r"\b5050\b"),
]


async def main() -> None:
    group_size = int(sys.argv[1]) if len(sys.argv) > 1 else 4
    deadline_s = float(sys.argv[2]) if len(sys.argv) > 2 else 20.0
    base_url = os.environ.get("OPENAI_BASE_URL")
    print(f"[cfg] OPENAI_BASE_URL = {base_url or '(unset — defaults)'}")
    print(f"[cfg] group_size      = {group_size}")
    print(f"[cfg] deadline_s      = {deadline_s}s per member")

    traces = TraceWriter(Path(__file__).parent / "traces" / "03_grpo")
    passthrough = {k: v for k, v in os.environ.items() if k.startswith(("OPENAI_", "CODEX_"))}

    async with CodexSession.spawn(env=passthrough, log_rpc_path=str(traces.rpc_log_path())) as session:
        for prompt, regex in TASKS:
            print(f"\n=== GROUP: {prompt!r} ===")
            t0 = time.perf_counter()
            members, stats = await single_turn_group(
                session,
                prompt=prompt,
                verifier=RegexVerifier(regex),
                k=group_size,
                timeout=deadline_s,
            )
            wall = time.perf_counter() - t0
            print(f"  wall={wall:.2f}s mean_reward={stats.mean_reward:.2f} std={stats.std_reward:.2f}")
            for m in members:
                final = (m.turn.final_text if m.turn else "")[:60]
                print(
                    f"    {m.member_id}  r={m.reward:.1f} adv={m.advantage:+.2f} "
                    f"t={m.elapsed_s:5.2f}s  → {final!r}"
                )
            traces.write_group(members, stats=stats, metadata={"prompt": prompt, "regex": regex})


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        sys.exit(130)
