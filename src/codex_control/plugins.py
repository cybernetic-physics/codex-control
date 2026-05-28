"""Typed facade for codex's plugin/marketplace JSON-RPC verbs.

These are present in every modern ``codex app-server`` (>=0.128) but
not yet wrapped by :class:`CodexSession`. The shape is small enough
that the right place for them is here rather than as a separate
package: install a plugin, wait for its MCP server to come up, drive
it via ``mcpServer/tool/call`` when we want to bypass the model.

The orchestration story for *multiple* CUA implementations
(`computer-use@linux-cua` from this repo, the macOS bundled
`computer-use@openai-bundled`, agent-sh's, …) is also here: the
``CuaProvider`` abstraction picks one at session-setup time.
"""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Iterable, Mapping, Optional

from .mcp import McpToolResult
from .session import CodexSession


log = logging.getLogger(__name__)


# ---------------------------------------------------------------------
# Method constants. Kept loose strings (not on `M`) because they're
# under-development per the app-server README and may rename.
# ---------------------------------------------------------------------

PLUGIN_LIST = "plugin/list"
PLUGIN_INSTALL = "plugin/install"
PLUGIN_UNINSTALL = "plugin/uninstall"
MCP_SERVER_STATUS_LIST = "mcpServerStatus/list"
MCP_SERVER_TOOL_CALL = "mcpServer/tool/call"
MCP_SERVER_STARTUP_UPDATED = "mcpServer/startupStatus/updated"


# ---------------------------------------------------------------------
# Data classes (mostly just to give callers IDE autocompletion;
# everything else stays as raw dicts to survive schema drift).
# ---------------------------------------------------------------------


@dataclass(slots=True)
class MarketplaceEntry:
    name: str
    kind: str | None
    plugins: list[dict[str, Any]]


@dataclass(slots=True)
class McpServerStatus:
    name: str
    state: str | None
    tools: dict[str, Any]
    auth_status: str | None
    raw: dict[str, Any]


# ---------------------------------------------------------------------
# Facade
# ---------------------------------------------------------------------


class Plugins:
    """Thin async helper bound to one :class:`CodexSession`."""

    def __init__(self, session: CodexSession) -> None:
        self._s = session

    # --- list / install ----------------------------------------------

    async def list(
        self,
        *,
        cwds: Iterable[str] | None = None,
        marketplace_kinds: Iterable[str] | None = None,
        timeout: float = 30.0,
    ) -> list[MarketplaceEntry]:
        """List marketplaces visible to this session.

        ``cwds`` is the list of directories the server should search for
        local marketplaces (default: home-scoped only). Use this to point
        codex at a repo's own ``.agents/plugins/marketplace.json``.

        Lower-cased enum casing per the wire schema:
        ``local`` / ``workspace-directory`` / ``shared-with-me``. There
        is no ``remote`` kind; the curated remote catalogue piggybacks on
        ``local`` when the feature flag is on.
        """
        params: dict[str, Any] = {}
        if cwds is not None:
            params["cwds"] = list(cwds)
        if marketplace_kinds is not None:
            params["marketplaceKinds"] = list(marketplace_kinds)
        result = await self._s.request(PLUGIN_LIST, params, timeout=timeout)
        return [
            MarketplaceEntry(
                name=m.get("name", ""),
                kind=m.get("kind"),
                plugins=list(m.get("plugins") or []),
            )
            for m in result.get("marketplaces", [])
        ]

    async def install(
        self,
        plugin_name: str,
        *,
        marketplace_path: str | None = None,
        remote_marketplace_name: str | None = None,
        timeout: float = 120.0,
    ) -> dict[str, Any]:
        """Install a plugin from a local marketplace.json or the remote
        bundled marketplace.

        Exactly one of ``marketplace_path`` (absolute path to a
        ``marketplace.json`` file) or ``remote_marketplace_name`` (e.g.
        ``"openai-bundled"``) must be passed.
        """
        params: dict[str, Any] = {"pluginName": plugin_name}
        if marketplace_path is not None:
            params["marketplacePath"] = marketplace_path
        if remote_marketplace_name is not None:
            params["remoteMarketplaceName"] = remote_marketplace_name
        return await self._s.request(PLUGIN_INSTALL, params, timeout=timeout)

    async def uninstall(
        self,
        plugin_name: str,
        *,
        marketplace_name: str,
        timeout: float = 30.0,
    ) -> dict[str, Any]:
        return await self._s.request(
            PLUGIN_UNINSTALL,
            {"pluginName": plugin_name, "marketplaceName": marketplace_name},
            timeout=timeout,
        )

    # --- MCP status / call --------------------------------------------

    async def mcp_status(
        self,
        *,
        server: str | None = None,
        timeout: float = 10.0,
    ) -> list[McpServerStatus]:
        """Return current MCP server status entries. Optionally filter."""
        result = await self._s.request(MCP_SERVER_STATUS_LIST, {}, timeout=timeout)
        entries = []
        for srv in result.get("data", []) or result.get("servers", []):
            if server is not None and srv.get("name") != server:
                continue
            entries.append(McpServerStatus(
                name=srv.get("name", ""),
                state=srv.get("startupState") or srv.get("status") or srv.get("state"),
                tools=dict(srv.get("tools") or {}),
                auth_status=srv.get("authStatus"),
                raw=srv,
            ))
        return entries

    async def wait_for_mcp_running(
        self,
        server: str,
        *,
        timeout: float = 30.0,
        poll_interval: float = 0.25,
    ) -> McpServerStatus:
        """Block until `server` enters a Running-ish state.

        Codex doesn't fire `startupStatus/updated` notifications until
        someone first invokes a tool on the server (it's a lazy spawn).
        So we poll. ``timeout`` is the total wall budget.
        """
        deadline = asyncio.get_event_loop().time() + timeout
        last: McpServerStatus | None = None
        while asyncio.get_event_loop().time() < deadline:
            entries = await self.mcp_status(server=server, timeout=5.0)
            if entries:
                last = entries[0]
                state = (last.state or "").lower()
                if state in {"running", "ready"} or last.tools:
                    return last
                if state in {"failed", "stopped", "errored", "error"}:
                    raise RuntimeError(f"{server} startup ended in state={last.state}: {last.raw.get('error')}")
            await asyncio.sleep(poll_interval)
        raise TimeoutError(f"{server} did not reach Running within {timeout}s; last={last}")

    async def call_tool(
        self,
        thread_id: str,
        server: str,
        tool: str,
        *,
        arguments: Mapping[str, Any] | None = None,
        timeout: float = 60.0,
    ) -> McpToolResult:
        """Direct ``mcpServer/tool/call`` — bypass the model, useful for
        golden trajectories and unit tests of the server side. Returns a
        typed :class:`McpToolResult` (the content-block walking lives
        inside the result type, not at the call site)."""
        raw = await self._s.request(
            MCP_SERVER_TOOL_CALL,
            {
                "threadId": thread_id,
                "server": server,
                "tool": tool,
                "arguments": dict(arguments or {}),
            },
            timeout=timeout,
        )
        return McpToolResult(raw)


# ---------------------------------------------------------------------
# CUA provider — the multi-backend orchestration point.
# ---------------------------------------------------------------------


@dataclass(slots=True)
class CuaProvider:
    """One way to obtain a `computer-use` MCP server in a session.

    The orchestration layer accepts a list of providers and picks the
    first one whose ``ensure`` succeeds. That lets a single experiment
    run against ``codex-cua-linux`` on Linux, the macOS bundled plugin
    on macOS, or ``agent-sh/computer-use-linux`` if the user prefers
    that flavour — without the verifier / reward code knowing which
    one ran.
    """

    name: str
    """Human label, e.g. ``"linux-cua"`` or ``"openai-bundled"``."""

    plugin_name: str = "computer-use"
    """Codex plugin id within ``marketplace``."""

    server_name: str = "computer-use"
    """MCP server name the plugin registers. Tools end up under
    ``mcp__<server_name_underscored>__*`` in codex; we assert this here
    so verifiers can rely on it."""

    marketplace_path: str | None = None
    """Local ``marketplace.json`` to install from. Mutually exclusive
    with ``remote_marketplace_name``."""

    remote_marketplace_name: str | None = None
    """Remote marketplace (``"openai-bundled"`` for the macOS plugin)."""


async def ensure_cua_provider(
    session: CodexSession,
    provider: CuaProvider,
    *,
    timeout: float = 60.0,
    probe_tool: str = "list_apps",
    cwd: str = "/tmp",
) -> McpServerStatus:
    """Install the provider's plugin if needed, force its MCP server to
    spawn via a no-op tool call, and return its status. Idempotent.

    Most experiments will call this once per session right after
    handshake. The probe tool defaults to ``list_apps`` (the macOS
    contract's read-only enumeration); pass ``probe_tool=None`` to
    skip the spawn nudge if your provider doesn't support it.
    """
    plugins = Plugins(session)

    # Already installed?
    cwds = []
    if provider.marketplace_path:
        # The marketplace listing key is the parent dir, not the JSON path.
        import os as _os
        parent = _os.path.dirname(provider.marketplace_path)
        # Walk up to the directory just above .agents/ or .claude-plugin/.
        for marker in (".agents", ".claude-plugin"):
            if marker in parent.split(_os.sep):
                idx = parent.split(_os.sep).index(marker)
                cwds.append(_os.sep.join(parent.split(_os.sep)[:idx]))
                break
        else:
            cwds.append(parent)
    listing = await plugins.list(cwds=cwds or None)
    already = any(
        any(p.get("id") == f"{provider.plugin_name}@{m.name}" and p.get("installed")
            for p in m.plugins)
        for m in listing
    )
    if not already:
        await plugins.install(
            provider.plugin_name,
            marketplace_path=provider.marketplace_path,
            remote_marketplace_name=provider.remote_marketplace_name,
            timeout=max(timeout, 120.0),
        )

    # Nudge: codex spawns MCP servers lazily on first tool call. We
    # invoke a cheap idempotent tool against a short-lived thread to
    # force the spawn; once that returns the server is in Running and
    # its tools/list has been cached.
    if probe_tool is not None:
        from .thread import Thread  # local import to break cycle
        thread = await session.start_thread(
            cwd=cwd, ephemeral=True, sandbox="read-only", approval_policy="never",
        )
        try:
            await plugins.call_tool(
                thread.thread_id, provider.server_name, probe_tool,
                arguments={}, timeout=min(timeout, 30.0),
            )
        except Exception as exc:
            log.debug("CUA spawn probe failed (%s); continuing", exc)
        finally:
            try:
                await thread.archive()
            except Exception:
                pass

    return await plugins.wait_for_mcp_running(provider.server_name, timeout=timeout)


async def first_available_cua(
    session: CodexSession,
    providers: Iterable[CuaProvider],
    *,
    timeout_each: float = 30.0,
) -> tuple[CuaProvider, McpServerStatus]:
    """Try each provider in order; return the first that works."""
    last_err: Exception | None = None
    for provider in providers:
        try:
            status = await ensure_cua_provider(session, provider, timeout=timeout_each)
            return provider, status
        except Exception as exc:  # noqa: BLE001 — surfacing any failure to caller below
            log.info("CUA provider %s failed: %s", provider.name, exc)
            last_err = exc
    if last_err is None:
        raise RuntimeError("no CUA providers configured")
    raise RuntimeError(f"no CUA provider available; last error: {last_err}") from last_err
