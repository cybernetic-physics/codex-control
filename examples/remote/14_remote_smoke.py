"""Remote smoke test against ``codex app-server --listen ws://...``.

Set ``REMOTE_URL`` and ``WS_TOKEN``. Requires the ``websocket`` extra.
"""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

from codex_control import CodexSession, TraceWriter
from codex_control.items import summarise


async def main() -> None:
    url = os.environ.get("REMOTE_URL", "ws://codex-server:8765")
    token = os.environ.get("WS_TOKEN")
    if not token:
        print("ERR: WS_TOKEN env var required", file=sys.stderr)
        sys.exit(2)

    traces = TraceWriter(Path(__file__).parent.parent / "traces" / "remote_14")
    print(f"[client] connecting to {url}")
    async with CodexSession.connect(
        url, token=token, log_rpc_path=str(traces.rpc_log_path()),
    ) as session:
        print(f"[client] initialized codexHome={session.server_info.get('codexHome')!r} "
              f"platformOs={session.server_info.get('platformOs')!r}")
        thread = await session.start_thread(
            cwd="/tmp", ephemeral=True, sandbox="read-only",
        )
        print(f"[client] remote thread/start → {thread.thread_id}")
        turn = await thread.run_turn(
            "Reply with the single word: pong",
            approval_policy="never", effort="low", timeout=120.0,
        )
        print(f"[client] turn status={turn.status} items={len(turn.items)}")
        for it in turn.items:
            print(f"  - {summarise(it)}")
        traces.write_turn(turn, rollout_id="remote_smoke")


if __name__ == "__main__":
    asyncio.run(main())
