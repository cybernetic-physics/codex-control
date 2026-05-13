"""Capability dossier — what the live ``codex app-server`` build supports."""
from __future__ import annotations

import asyncio
import dataclasses
import json
import sys
from pathlib import Path

from codex_control import CodexSession, TraceWriter, fetch_dossier


async def main() -> None:
    traces = TraceWriter(Path(__file__).parent / "traces" / "13_introspection")
    async with CodexSession.spawn(
        experimental_api=True,
        log_rpc_path=str(traces.rpc_log_path()),
    ) as session:
        dossier = await fetch_dossier(session)

    print("=== Server info ===")
    print(json.dumps(dossier.server_info, indent=2)[:600])

    if dossier.models:
        print("\n=== Models ===")
        for m in dossier.models[:12]:
            efforts = [e.get("effort") for e in m.get("reasoningEffortOptions", [])]
            print(f"  {m.get('id', '?'):<28} efforts={efforts}")

    if dossier.collaboration_modes:
        print("\n=== Collaboration modes ===")
        for m in dossier.collaboration_modes:
            print(f"  {m.get('mode', '?'):<10} name={m.get('name', '?')!r} effort={m.get('reasoning_effort')}")

    if dossier.experimental_features:
        print("\n=== Experimental features ===")
        for f in dossier.experimental_features[:30]:
            stage = f.get("stage", "?")
            enabled = f.get("enabled", "?")
            default = f.get("defaultEnabled", "?")
            print(f"  [{stage:<14}] enabled={enabled!s:5} default={default!s:5} name={f.get('name', '?')}")

    if dossier.model_provider_capabilities:
        print("\n=== Model-provider capabilities ===")
        print(json.dumps(dossier.model_provider_capabilities, indent=2)[:600])

    if dossier.errors:
        print(f"\n=== Read errors ===\n{dossier.errors}")

    out = traces.run_dir / "introspection.json"
    out.write_text(json.dumps(dataclasses.asdict(dossier), indent=2, default=str))
    print(f"\n[save] {out}")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        sys.exit(130)
