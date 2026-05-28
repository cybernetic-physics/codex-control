"""Typed helpers for driving Computer Use MCP tools.

This module is intentionally a thin layer over :mod:`codex_control.plugins`.
Plugin installation, MCP server lifecycle, and JSON-RPC transport stay owned
there; the helpers here give callers stable method names and typed views for
the ten ``computer-use`` tools.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping

from .mcp import McpToolResult
from .plugins import (
    CuaProvider,
    McpServerStatus,
    Plugins,
    ensure_cua_provider,
    first_available_cua,
)
from .session import CodexSession


DEFAULT_COMPUTER_USE_SERVER = "computer-use"


@dataclass(frozen=True, slots=True)
class ComputerUseApp:
    """One app/window entry returned by ``list_apps``."""

    app: str
    name: str | None = None
    raw: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ComputerUseState:
    """State snapshot returned by ``get_app_state``."""

    app: str
    raw: Mapping[str, Any]
    screenshot: bytes | None
    result: McpToolResult

    @property
    def accessibility_tree(self) -> list[Mapping[str, Any]]:
        tree = self.raw.get("accessibility_tree")
        if isinstance(tree, list):
            return [node for node in tree if isinstance(node, Mapping)]
        return []


class ComputerUseClient:
    """Convenience wrapper around ``Plugins.call_tool`` for one thread."""

    def __init__(
        self,
        plugins: Plugins,
        thread_id: str,
        *,
        server: str = DEFAULT_COMPUTER_USE_SERVER,
    ) -> None:
        self._plugins = plugins
        self.thread_id = thread_id
        self.server = server

    @classmethod
    def for_session(
        cls,
        session: CodexSession,
        thread_id: str,
        *,
        server: str = DEFAULT_COMPUTER_USE_SERVER,
    ) -> "ComputerUseClient":
        return cls(Plugins(session), thread_id, server=server)

    async def call(
        self,
        tool: str,
        arguments: Mapping[str, Any] | None = None,
        *,
        timeout: float = 60.0,
    ) -> McpToolResult:
        return await self._plugins.call_tool(
            self.thread_id,
            self.server,
            tool,
            arguments=arguments,
            timeout=timeout,
        )

    async def list_apps(self, *, timeout: float = 30.0) -> list[ComputerUseApp]:
        result = await self.call("list_apps", {}, timeout=timeout)
        payload = result.json()
        apps = _apps_payload(payload)
        return [
            ComputerUseApp(
                app=str(item.get("app", "")),
                name=str(item["name"]) if item.get("name") is not None else None,
                raw=item,
            )
            for item in apps
            if item.get("app")
        ]

    async def get_app_state(self, app: str, *, timeout: float = 60.0) -> ComputerUseState:
        result = await self.call("get_app_state", {"app": app}, timeout=timeout)
        payload = result.json()
        raw = payload if isinstance(payload, Mapping) else {}
        return ComputerUseState(
            app=str(raw.get("app") or app),
            raw=raw,
            screenshot=result.image_bytes(),
            result=result,
        )

    async def click(
        self,
        app: str,
        *,
        element_index: str | None = None,
        x: float | None = None,
        y: float | None = None,
        click_count: int | None = None,
        mouse_button: str | None = None,
        timeout: float = 60.0,
    ) -> McpToolResult:
        args: dict[str, Any] = {"app": app}
        args.update(_optional(
            element_index=element_index,
            x=x,
            y=y,
            click_count=click_count,
            mouse_button=mouse_button,
        ))
        return await self.call("click", args, timeout=timeout)

    async def perform_secondary_action(
        self,
        app: str,
        *,
        element_index: str,
        action: str,
        timeout: float = 60.0,
    ) -> McpToolResult:
        return await self.call(
            "perform_secondary_action",
            {"app": app, "element_index": element_index, "action": action},
            timeout=timeout,
        )

    async def set_value(
        self,
        app: str,
        *,
        element_index: str,
        value: str,
        timeout: float = 60.0,
    ) -> McpToolResult:
        return await self.call(
            "set_value",
            {"app": app, "element_index": element_index, "value": value},
            timeout=timeout,
        )

    async def select_text(
        self,
        app: str,
        *,
        element_index: str,
        text: str,
        prefix: str | None = None,
        suffix: str | None = None,
        selection: str | None = None,
        timeout: float = 60.0,
    ) -> McpToolResult:
        args: dict[str, Any] = {"app": app, "element_index": element_index, "text": text}
        args.update(_optional(prefix=prefix, suffix=suffix, selection=selection))
        return await self.call("select_text", args, timeout=timeout)

    async def scroll(
        self,
        app: str,
        *,
        element_index: str,
        direction: str,
        pages: float | None = None,
        timeout: float = 60.0,
    ) -> McpToolResult:
        args: dict[str, Any] = {
            "app": app,
            "element_index": element_index,
            "direction": direction,
        }
        args.update(_optional(pages=pages))
        return await self.call("scroll", args, timeout=timeout)

    async def drag(
        self,
        app: str,
        *,
        from_x: float,
        from_y: float,
        to_x: float,
        to_y: float,
        timeout: float = 60.0,
    ) -> McpToolResult:
        return await self.call(
            "drag",
            {"app": app, "from_x": from_x, "from_y": from_y, "to_x": to_x, "to_y": to_y},
            timeout=timeout,
        )

    async def press_key(self, app: str, key: str, *, timeout: float = 60.0) -> McpToolResult:
        return await self.call("press_key", {"app": app, "key": key}, timeout=timeout)

    async def type_text(self, app: str, text: str, *, timeout: float = 60.0) -> McpToolResult:
        return await self.call("type_text", {"app": app, "text": text}, timeout=timeout)


async def ensure_computer_use(
    session: CodexSession,
    provider: CuaProvider,
    *,
    timeout: float = 60.0,
    probe_tool: str = "list_apps",
    cwd: str = "/tmp",
) -> McpServerStatus:
    """Install/start one Computer Use provider and return its MCP status."""

    return await ensure_cua_provider(
        session,
        provider,
        timeout=timeout,
        probe_tool=probe_tool,
        cwd=cwd,
    )


async def first_available_computer_use(
    session: CodexSession,
    providers: Iterable[CuaProvider],
    *,
    timeout_each: float = 30.0,
) -> tuple[CuaProvider, McpServerStatus]:
    """Return the first configured Computer Use provider that starts."""

    return await first_available_cua(session, providers, timeout_each=timeout_each)


def _apps_payload(payload: Any) -> list[Mapping[str, Any]]:
    if isinstance(payload, Mapping):
        apps = payload.get("apps")
    else:
        apps = payload
    if not isinstance(apps, list):
        return []
    return [item for item in apps if isinstance(item, Mapping)]


def _optional(**items: Any) -> dict[str, Any]:
    return {key: value for key, value in items.items() if value is not None}


__all__ = [
    "ComputerUseApp",
    "ComputerUseClient",
    "ComputerUseState",
    "DEFAULT_COMPUTER_USE_SERVER",
    "ensure_computer_use",
    "first_available_computer_use",
]
