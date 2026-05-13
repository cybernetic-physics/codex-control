"""Prompt-control matrix: ``baseInstructions`` × ``developerInstructions``."""
from __future__ import annotations

import asyncio
import json
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

from codex_control import CodexSession, TraceWriter
from codex_control.items import last_agent_message


BRUTALIST = (
    "You are a brutalist Python coder. You answer EVERY request with exactly "
    "one valid Python expression on a single line. No comments. No prose. "
    "Just the line. If the user asks for a function, use lambda. Output ONLY code."
)

PROJECT_DEV_RULES = (
    "Project conventions for this repo:\n"
    "- Always include type hints.\n"
    "- Always include a one-line docstring that starts with 'Return ...'.\n"
    "- Always include the comment '# pure' on the same line as the def.\n"
)


@dataclass
class Config:
    label: str
    base: str | None
    developer: str | None


CONFIGS = [
    Config("A_defaults", None, None),
    Config("B_brutalist", BRUTALIST, None),
    Config("C_devrules", None, PROJECT_DEV_RULES),
    Config("D_both", BRUTALIST, PROJECT_DEV_RULES),
]

TASK = "Write a Python function that returns the n-th Fibonacci number."


async def run_config(session: CodexSession, cfg: Config) -> dict:
    with tempfile.TemporaryDirectory(prefix=f"prompt-{cfg.label}-") as workdir:
        thread = await session.start_thread(
            cwd=workdir, ephemeral=True, sandbox="read-only",
            approval_policy="never",
            base_instructions=cfg.base,
            developer_instructions=cfg.developer,
        )
        t0 = time.perf_counter()
        turn = await thread.run_turn(
            TASK, cwd=workdir, approval_policy="never", effort="low", timeout=120.0,
        )
        await thread.archive()
        wall = time.perf_counter() - t0
        return {
            "label": cfg.label, "wall_s": wall, "status": turn.status,
            "final": last_agent_message(turn.items),
        }


def heuristics(text: str) -> dict:
    lower = text.lower()
    return {
        "len_chars": len(text),
        "n_lines": text.count("\n") + 1,
        "uses_def": " def " in (" " + text) or text.startswith("def "),
        "uses_lambda": "lambda" in lower,
        "has_type_hint": "->" in text or ": int" in text or ": float" in text,
        "has_docstring": '"""' in text or "'''" in text,
        "has_pure_comment": "# pure" in lower,
    }


async def main() -> None:
    traces = TraceWriter(Path(__file__).parent / "traces" / "10_prompt_control")
    async with CodexSession.spawn(log_rpc_path=str(traces.rpc_log_path())) as session:
        print(f"[task] {TASK!r}\n")
        results = []
        for cfg in CONFIGS:
            print(f"=== {cfg.label} base={cfg.base is not None} dev={cfg.developer is not None} ===")
            r = await run_config(session, cfg)
            r["heuristics"] = heuristics(r["final"])
            results.append(r)
            print(r["final"][:500])
            print(f"  → {r['heuristics']}\n")

    print("=" * 70)
    print(f"{'config':<14} {'len':>4} {'lines':>5} {'def':>4} {'lam':>4} {'hint':>4} {'doc':>4} {'pure':>4}")
    for r in results:
        h = r["heuristics"]
        print(
            f"{r['label']:<14} {h['len_chars']:>4d} {h['n_lines']:>5d} "
            f"{'Y' if h['uses_def'] else '.':>4} "
            f"{'Y' if h['uses_lambda'] else '.':>4} "
            f"{'Y' if h['has_type_hint'] else '.':>4} "
            f"{'Y' if h['has_docstring'] else '.':>4} "
            f"{'Y' if h['has_pure_comment'] else '.':>4}"
        )
    (traces.run_dir / "matrix.json").write_text(json.dumps(results, indent=2, default=str))


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        sys.exit(130)
