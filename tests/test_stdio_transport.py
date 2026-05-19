from __future__ import annotations

import asyncio
import json
import sys
import textwrap

import pytest

from codex_control.transport.stdio import StdioTransport


@pytest.mark.asyncio
async def test_stdio_transport_reads_large_jsonrpc_frame(tmp_path) -> None:
    """Codex app-server can emit JSON-RPC frames larger than 64 KiB."""

    script = tmp_path / "emit_large_frame.py"
    payload = "x" * (70 * 1024)
    script.write_text(
        textwrap.dedent(
            f"""
            import json
            import sys

            frame = {{"jsonrpc": "2.0", "method": "large", "params": {{"payload": {payload!r}}}}}
            sys.stdout.write(json.dumps(frame) + "\\n")
            sys.stdout.flush()
            """
        )
    )

    transport = StdioTransport(sys.executable, args=(str(script),))
    await transport.start()
    try:
        frame = await asyncio.wait_for(anext(transport.__aiter__()), timeout=5)
    finally:
        await transport.close()

    assert frame["method"] == "large"
    assert frame["params"]["payload"] == payload
