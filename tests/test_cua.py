from __future__ import annotations

import base64
import json
from typing import Any

import pytest

from codex_control import (
    ComputerUseClient,
    CuaProvider,
    McpServerStatus,
    Plugins,
    ensure_computer_use,
)
import codex_control.cua as cua


PNG = b"\x89PNG"


class FakeSession:
    def __init__(self) -> None:
        self.requests: list[tuple[str, dict[str, Any], float]] = []

    async def request(
        self,
        method: str,
        params: dict[str, Any],
        *,
        timeout: float,
    ) -> dict[str, Any]:
        self.requests.append((method, params, timeout))
        tool = params["tool"]
        if tool == "list_apps":
            return {
                "content": [
                    {
                        "type": "text",
                        "text": json.dumps(
                            {
                                "apps": [
                                    {
                                        "app": "firefox",
                                        "name": "Mozilla Firefox",
                                        "window_id": "0x01",
                                    }
                                ]
                            }
                        ),
                    }
                ]
            }
        if tool == "get_app_state":
            return {
                "content": [
                    {
                        "type": "text",
                        "text": json.dumps(
                            {
                                "app": params["arguments"]["app"],
                                "accessibility_tree": [{"element_index": "0"}],
                            }
                        ),
                    },
                    {
                        "type": "image",
                        "data": base64.b64encode(PNG).decode("ascii"),
                        "mimeType": "image/png",
                    },
                ]
            }
        return {"content": [{"type": "text", "text": json.dumps({"ok": True})}]}


@pytest.mark.asyncio
async def test_computer_use_client_lists_apps_and_state() -> None:
    session = FakeSession()
    client = ComputerUseClient(Plugins(session), "thread-1")

    apps = await client.list_apps()
    state = await client.get_app_state("firefox")

    assert apps[0].app == "firefox"
    assert apps[0].name == "Mozilla Firefox"
    assert state.app == "firefox"
    assert state.screenshot == PNG
    assert state.accessibility_tree == [{"element_index": "0"}]
    assert session.requests[0][1] == {
        "threadId": "thread-1",
        "server": "computer-use",
        "tool": "list_apps",
        "arguments": {},
    }


@pytest.mark.asyncio
async def test_action_helpers_omit_unset_optional_arguments() -> None:
    session = FakeSession()
    client = ComputerUseClient(Plugins(session), "thread-1")

    await client.click("firefox", element_index="0")
    await client.press_key("firefox", "Return")
    await client.type_text("firefox", "hello")

    assert session.requests[0][1]["arguments"] == {"app": "firefox", "element_index": "0"}
    assert session.requests[1][1]["arguments"] == {"app": "firefox", "key": "Return"}
    assert session.requests[2][1]["arguments"] == {"app": "firefox", "text": "hello"}


@pytest.mark.asyncio
async def test_ensure_computer_use_preserves_provider_boundary(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[Any, CuaProvider, float, str, str]] = []
    status = McpServerStatus(
        name="computer-use",
        state="running",
        tools={},
        auth_status=None,
        raw={},
    )

    async def fake_ensure(
        session: Any,
        provider: CuaProvider,
        *,
        timeout: float,
        probe_tool: str,
        cwd: str,
    ) -> McpServerStatus:
        calls.append((session, provider, timeout, probe_tool, cwd))
        return status

    monkeypatch.setattr(cua, "ensure_cua_provider", fake_ensure)
    session = FakeSession()
    provider = CuaProvider(name="linux-cua", marketplace_path="/tmp/marketplace.json")

    got = await ensure_computer_use(
        session,
        provider,
        timeout=12.0,
        probe_tool="list_apps",
        cwd="/workspace",
    )

    assert got is status
    assert calls == [(session, provider, 12.0, "list_apps", "/workspace")]
