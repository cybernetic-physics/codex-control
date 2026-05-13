"""Subprocess-stdio transport.

Spawns ``codex app-server --listen stdio://`` and frames JSON-RPC with
newline-delimited JSON. Each line on the child's stdout is one frame;
the child's stderr is drained on a background task so the pipe never
blocks (we log it if a stderr callback is configured).
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
from typing import AsyncIterator, Callable, Optional, Sequence

from ..errors import TransportError
from ..protocol.jsonrpc import JsonObject
from .base import Transport

log = logging.getLogger(__name__)


class StdioTransport(Transport):
    """One ``codex app-server`` subprocess, framed by ``\\n``.

    Parameters
    ----------
    codex_bin
        Path or name of the ``codex`` binary. Resolved via ``$PATH``.
    args
        Subcommand + flags. Defaults to ``["app-server", "--listen", "stdio://"]``.
    env
        Extra environment variables merged onto the parent's. Use this
        to wire ``OPENAI_BASE_URL`` / ``CODEX_HOME`` per session.
    cwd
        Working directory for the subprocess. The app-server itself
        doesn't care; per-thread ``cwd`` is set on ``thread/start``.
    stderr_cb
        Optional callable invoked with each (decoded) stderr line. If
        ``None``, stderr is logged at DEBUG level.
    """

    def __init__(
        self,
        codex_bin: str = "codex",
        *,
        args: Sequence[str] = ("app-server", "--listen", "stdio://"),
        env: Optional[dict[str, str]] = None,
        cwd: Optional[str] = None,
        stderr_cb: Optional[Callable[[str], None]] = None,
    ) -> None:
        self._codex_bin = codex_bin
        self._args = list(args)
        self._env_overrides = env or {}
        self._cwd = cwd
        self._stderr_cb = stderr_cb

        self._proc: Optional[asyncio.subprocess.Process] = None
        self._stderr_task: Optional[asyncio.Task[None]] = None
        self._closed = False

    async def start(self) -> None:
        """Spawn the subprocess. Must be called once before iteration/send."""
        if self._proc is not None:
            return
        env = os.environ.copy()
        env.update(self._env_overrides)
        try:
            self._proc = await asyncio.create_subprocess_exec(
                self._codex_bin,
                *self._args,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=env,
                cwd=self._cwd,
            )
        except FileNotFoundError as exc:
            raise TransportError(
                f"failed to launch {self._codex_bin!r}: {exc}"
            ) from exc
        self._stderr_task = asyncio.create_task(self._drain_stderr())

    async def __aenter__(self) -> "StdioTransport":
        await self.start()
        return self

    async def send(self, frame: JsonObject) -> None:
        if self._proc is None or self._proc.stdin is None:
            raise TransportError("transport not started")
        if self._proc.returncode is not None:
            raise TransportError(
                f"subprocess exited with code {self._proc.returncode}"
            )
        data = (json.dumps(frame, separators=(",", ":")) + "\n").encode("utf-8")
        try:
            self._proc.stdin.write(data)
            await self._proc.stdin.drain()
        except (BrokenPipeError, ConnectionResetError) as exc:
            raise TransportError(f"send failed: {exc}") from exc

    async def __aiter__(self) -> AsyncIterator[JsonObject]:
        if self._proc is None or self._proc.stdout is None:
            raise TransportError("transport not started")
        async for raw in self._proc.stdout:
            line = raw.decode("utf-8", errors="replace").strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError as exc:
                log.warning("dropping non-JSON line from codex stdout: %r (%s)", line[:200], exc)
                continue
            if isinstance(obj, dict):
                yield obj
            else:
                log.warning("dropping non-object JSON from codex stdout: %r", line[:200])

    async def _drain_stderr(self) -> None:
        assert self._proc is not None and self._proc.stderr is not None
        async for raw in self._proc.stderr:
            line = raw.decode("utf-8", errors="replace").rstrip()
            if self._stderr_cb is not None:
                with contextlib.suppress(Exception):
                    self._stderr_cb(line)
            else:
                log.debug("codex stderr: %s", line)

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        if self._proc is not None and self._proc.returncode is None:
            with contextlib.suppress(ProcessLookupError):
                self._proc.terminate()
            try:
                await asyncio.wait_for(self._proc.wait(), timeout=5)
            except asyncio.TimeoutError:
                with contextlib.suppress(ProcessLookupError):
                    self._proc.kill()
                await self._proc.wait()
        if self._stderr_task is not None:
            self._stderr_task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await self._stderr_task

    @property
    def pid(self) -> Optional[int]:
        return self._proc.pid if self._proc is not None else None
