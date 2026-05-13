"""``thread/inject_items``: developer-role hint and few-shot demonstration.

Uses :func:`build_developer_hint` and :func:`build_demo_pair` rather
than hand-crafted Responses-API item dicts.
"""
from __future__ import annotations

import asyncio
import json
import sys
import tempfile
from pathlib import Path

from codex_control import CodexSession, TraceWriter, build_demo_pair, build_developer_hint
from codex_control.items import last_agent_message


HARD_QUESTION = (
    "What is the airspeed velocity of an unladen European swallow? "
    "Give a single number in meters per second. Answer with only the number."
)

HINT = build_developer_hint(
    "Hint for the next user question: the canonical figure from "
    "ornithology studies is roughly 11 m/s for the European swallow. "
    "Use this figure when answering."
)

DEMO = build_demo_pair(
    "Format your answers like: 'NUMBER: <n>, UNIT: <u>'. What is 6 times 7?",
    "NUMBER: 42, UNIT: dimensionless",
)
FORMAT_TEST_QUESTION = "What is the square root of 144? Use the same answer format."


async def run(session: CodexSession, label: str, items, question):
    with tempfile.TemporaryDirectory(prefix=f"inj-{label}-") as workdir:
        thread = await session.start_thread(
            cwd=workdir, ephemeral=False, sandbox="read-only",
            approval_policy="never",
        )
        injected = False
        if items:
            try:
                await thread.inject_items(items)
                injected = True
            except Exception as exc:
                print(f"  [warn] inject failed: {exc}")
        turn = await thread.run_turn(
            question, cwd=workdir, approval_policy="never", effort="low", timeout=120.0,
        )
        await thread.archive()
        return {"label": label, "injected": injected, "final": last_agent_message(turn.items)}


async def main() -> None:
    traces = TraceWriter(Path(__file__).parent / "traces" / "12_inject")
    async with CodexSession.spawn(log_rpc_path=str(traces.rpc_log_path())) as session:
        print("\n=== Scenario 1: developer-role hint ===")
        control = await run(session, "ctrl_no_hint", None, HARD_QUESTION)
        hinted = await run(session, "with_hint", [HINT], HARD_QUESTION)
        for r in (control, hinted):
            print(f"  {r['label']:14} injected={r['injected']!s:5} final={r['final'][:80]!r}")
        print(f"  control has '11'={('11' in control['final'])} hinted has '11'={('11' in hinted['final'])}")

        print("\n=== Scenario 2: format-demonstration few-shot ===")
        ctl2 = await run(session, "ctrl_no_demo", None, FORMAT_TEST_QUESTION)
        demo = await run(session, "with_demo", DEMO, FORMAT_TEST_QUESTION)
        for r in (ctl2, demo):
            print(f"  {r['label']:14} injected={r['injected']!s:5} final={r['final'][:80]!r}")
        ctl2_fmt = "NUMBER:" in ctl2["final"] and "UNIT:" in ctl2["final"]
        demo_fmt = "NUMBER:" in demo["final"] and "UNIT:" in demo["final"]
        print(f"  control format={ctl2_fmt} demo format={demo_fmt}")

        (traces.run_dir / "inject.json").write_text(json.dumps({
            "scenario_1": {"control": control, "hinted": hinted},
            "scenario_2": {"control": ctl2, "demo": demo},
        }, indent=2, default=str))


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        sys.exit(130)
