"""``turn/start.outputSchema``-constrained finals graded by :class:`JsonSchemaVerifier`."""
from __future__ import annotations

import asyncio
import json
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from codex_control import (
    CodexSession,
    JsonSchemaVerifier,
    TraceWriter,
    VerifierResult,
)


@dataclass
class SchemaTask:
    label: str
    prompt: str
    schema: dict
    grader: Callable[[dict[str, Any]], VerifierResult]


def arithmetic(obj: dict[str, Any]) -> VerifierResult:
    ok = obj.get("answer") == 391
    return VerifierResult(reward=1.0 if ok else 0.0, ok=ok,
                          reason=f"got {obj.get('answer')!r} expected 391")


def classification(obj: dict[str, Any]) -> VerifierResult:
    ok = obj.get("category") == "fruit"
    return VerifierResult(reward=1.0 if ok else 0.0, ok=ok,
                          reason=f"got {obj.get('category')!r} expected fruit")


def rubric(obj: dict[str, Any]) -> VerifierResult:
    scores = obj.get("scores") or {}
    needed = ("correctness", "readability", "efficiency")
    if not all(k in scores for k in needed):
        return VerifierResult(reward=0.0, ok=False, reason=f"missing keys; got {list(scores.keys())}")
    for k in needed:
        v = scores[k]
        if not isinstance(v, (int, float)) or not 0 <= v <= 10:
            return VerifierResult(reward=0.0, ok=False, reason=f"{k}={v} out of range")
    return VerifierResult(reward=1.0, ok=True, reason="all in range")


TASKS = [
    SchemaTask(
        label="arithmetic",
        prompt="Compute 17 * 23. Reply with a JSON object matching the schema.",
        schema={
            "type": "object",
            "properties": {"answer": {"type": "integer"}, "method": {"type": "string"}},
            "required": ["answer", "method"],
            "additionalProperties": False,
        },
        grader=arithmetic,
    ),
    SchemaTask(
        label="classification",
        prompt="Classify the word 'apple' into one of: fruit, animal, vehicle, person. Reply as JSON.",
        schema={
            "type": "object",
            "properties": {
                "category": {"type": "string", "enum": ["fruit", "animal", "vehicle", "person"]},
                "confidence": {"type": "number", "minimum": 0, "maximum": 1},
            },
            "required": ["category", "confidence"],
            "additionalProperties": False,
        },
        grader=classification,
    ),
    SchemaTask(
        label="code_rubric",
        prompt=(
            "Score the snippet on three axes (correctness, readability, efficiency), "
            "each on a 0-10 scale. Snippet: ```python\\ndef f(x):\\n    return [i for i "
            "in range(x) if i%2 == 0]\\n```. Reply as JSON."
        ),
        schema={
            "type": "object",
            "properties": {
                "scores": {
                    "type": "object",
                    "properties": {
                        "correctness": {"type": "number", "minimum": 0, "maximum": 10},
                        "readability": {"type": "number", "minimum": 0, "maximum": 10},
                        "efficiency": {"type": "number", "minimum": 0, "maximum": 10},
                    },
                    "required": ["correctness", "readability", "efficiency"],
                    "additionalProperties": False,
                },
                "rationale": {"type": "string"},
            },
            "required": ["scores", "rationale"],
            "additionalProperties": False,
        },
        grader=rubric,
    ),
]


async def main() -> None:
    traces = TraceWriter(Path(__file__).parent / "traces" / "11_outputschema")
    async with CodexSession.spawn(log_rpc_path=str(traces.rpc_log_path())) as session:
        results = []
        for task in TASKS:
            print(f"\n=== {task.label} ===")
            with tempfile.TemporaryDirectory(prefix=f"sch-{task.label}-") as workdir:
                thread = await session.start_thread(
                    cwd=workdir, ephemeral=True, sandbox="read-only",
                    approval_policy="never",
                )
                try:
                    turn = await thread.run_turn(
                        task.prompt,
                        cwd=workdir, approval_policy="never", effort="low",
                        output_schema=task.schema, timeout=120.0,
                    )
                    schema_supported = True
                except Exception as exc:
                    print(f"  [warn] outputSchema rejected: {exc!r}")
                    turn = await thread.run_turn(
                        task.prompt,
                        cwd=workdir, approval_policy="never", effort="low", timeout=120.0,
                    )
                    schema_supported = False
                await thread.archive()

            verifier = JsonSchemaVerifier(task.grader)
            verdict = verifier(turn)
            print(f"  parsed={verdict.info.get('parsed')}")
            print(f"  reward={verdict.reward:.2f} ok={verdict.ok} reason={verdict.reason}")
            results.append({
                "label": task.label,
                "schema_supported": schema_supported,
                "reward": verdict.reward,
                "ok": verdict.ok,
                "parsed": verdict.info.get("parsed"),
                "final": verdict.info.get("final_text"),
            })
    total = sum(r["reward"] for r in results)
    print(f"\n[total reward] {total:.2f} / {len(results)}")
    (traces.run_dir / "summary.json").write_text(json.dumps(results, indent=2, default=str))


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        sys.exit(130)
