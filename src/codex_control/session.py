""":class:`CodexSession` — the JSON-RPC dispatcher on top of a transport.

This is the only class in the library that touches a transport directly.
Everything user-facing (threads, turns, rollouts, RLVR loops) is built on
top of these primitives:

* :meth:`request` — send a request, await its response
* :meth:`notify`  — send a notification (fire and forget)
* :meth:`subscribe` — register an async queue that receives notifications
* :meth:`run_handshake` — run ``initialize`` + ``initialized`` once
* :meth:`start_thread` — sugar for ``thread/start`` returning a :class:`Thread`

Lifecycle is `async with`:

.. code-block:: python

    async with CodexSession.spawn() as session:
        thread = await session.start_thread()
        turn = await thread.run_turn("hello")

The class is designed so that the same logic works against any
:class:`~codex_control.transport.Transport` — stdio, websocket, or a
fake transport in tests.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from typing import Any, Callable, Mapping, Optional, TYPE_CHECKING

from . import _version
from .errors import HandshakeError, ProtocolError, RpcError, TransportError
from .handlers import ApprovalHandler
from .protocol.jsonrpc import (
    JsonObject,
    build_error_response,
    build_notification,
    build_request,
    build_response,
    parse_frame,
)
from .protocol.methods import M, Notif, ServerReq
from .transport.base import Transport
from .transport.stdio import StdioTransport

if TYPE_CHECKING:
    from .thread import Thread

log = logging.getLogger(__name__)


# -----------------------------------------------------------------------
# Subscription
# -----------------------------------------------------------------------

class Subscription:
    """An async queue of notification payloads.

    Returned by :meth:`CodexSession.subscribe`. Subscriptions are
    self-cleaning: use them as an async context manager or call
    :meth:`close` to remove the underlying queue from the session's
    dispatch tables.

    Iteration yields ``{"method": str, "params": dict}`` dicts in the
    order the server posted them. The subscription buffers
    notifications received between creation and iteration, so callers
    can subscribe *before* firing a request and not lose early events.
    That ordering matters: ``item/started`` notifications can land
    inside the same dispatch tick that resolves ``turn/start``.
    """

    def __init__(self, session: "CodexSession", method: Optional[str]) -> None:
        self._session = session
        self._method = method
        self._queue: asyncio.Queue[JsonObject] = asyncio.Queue()
        self._closed = False

    async def get(self) -> JsonObject:
        return await self._queue.get()

    def __aiter__(self) -> "Subscription":
        return self

    async def __anext__(self) -> JsonObject:
        try:
            return await self._queue.get()
        except asyncio.CancelledError:  # pragma: no cover
            raise StopAsyncIteration

    async def __aenter__(self) -> "Subscription":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        self.close()

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._session._drop_subscription(self)

    # Used by the session's dispatch loop.
    def _put_nowait(self, payload: JsonObject) -> None:
        if not self._closed:
            self._queue.put_nowait(payload)


# -----------------------------------------------------------------------
# Session
# -----------------------------------------------------------------------

RpcLogger = Callable[[str, JsonObject], None]
"""Callable signature for the wire-traffic log hook.

Called with ``(direction, frame)``: direction is ``"send"`` / ``"recv"``
/ ``"stderr"`` (the last only when an stdio transport drains stderr).
"""


def _default_rpc_logger_factory(path: str) -> RpcLogger:
    """File-backed wire logger writing one JSONL entry per frame.

    Used when callers pass ``log_rpc_path=`` to :meth:`CodexSession.spawn`.
    """
    import json as _json

    fp = open(path, "a", buffering=1, encoding="utf-8")

    def _emit(direction: str, frame: JsonObject) -> None:
        try:
            fp.write(_json.dumps({"dir": direction, **frame}) + "\n")
        except Exception:  # pragma: no cover
            log.exception("rpc logger write failed")

    _emit.close = fp.close  # type: ignore[attr-defined]
    return _emit


class CodexSession:
    """One JSON-RPC session against a Codex app-server.

    Build via :meth:`spawn` (stdio) or :meth:`connect` (websocket), or
    pass a custom transport via the constructor.

    The session lifecycle:

    1. Construct (no I/O).
    2. ``async with session:`` — opens the transport, runs the handshake,
       starts the reader loop.
    3. ``request`` / ``notify`` / ``subscribe`` / ``start_thread`` —
       freely interleaved.
    4. Exit — gracefully closes the transport and cancels the reader.
    """

    # --- construction --------------------------------------------------

    def __init__(
        self,
        transport: Transport,
        *,
        client_name: str = "codex-control",
        client_title: str = "codex-control client",
        client_version: str = _version.__version__,
        experimental_api: bool = False,
        approval_handler: Optional[ApprovalHandler] = None,
        rpc_logger: Optional[RpcLogger] = None,
        request_timeout: float = 600.0,
    ) -> None:
        self._transport = transport
        self._client_name = client_name
        self._client_title = client_title
        self._client_version = client_version
        self._experimental_api = experimental_api
        self._approval_handler = approval_handler
        self._rpc_logger = rpc_logger
        self._request_timeout = request_timeout

        # Wire-state
        self._next_id = 0
        self._pending: dict[Any, asyncio.Future[Any]] = {}
        self._method_subs: dict[str, list[Subscription]] = {}
        self._wildcard_subs: list[Subscription] = []
        self._reader: Optional[asyncio.Task[None]] = None
        self._closing = False
        self._started = False

        # Result of the ``initialize`` request, exposed for callers.
        self.server_info: JsonObject = {}

    # --- factory helpers ----------------------------------------------

    @classmethod
    def spawn(
        cls,
        codex_bin: str = "codex",
        *,
        env: Optional[Mapping[str, str]] = None,
        listen: str = "stdio://",
        log_rpc_path: Optional[str] = None,
        approval_handler: Optional[ApprovalHandler] = None,
        experimental_api: bool = False,
        client_name: str = "codex-control",
        client_version: str = _version.__version__,
        stderr_cb: Optional[Callable[[str], None]] = None,
    ) -> "CodexSession":
        """Construct a session backed by a local ``codex app-server`` subprocess.

        Equivalent to the ``AppServer`` class in the experiments. The
        ``env`` mapping is merged onto the parent's environment; this is
        the hook for ``OPENAI_BASE_URL=...`` (point the agent at a
        trainable-policy proxy) and ``CODEX_HOME=...`` (use a clean
        config instead of the user's ``~/.codex``).
        """
        transport = StdioTransport(
            codex_bin,
            args=("app-server", "--listen", listen),
            env=dict(env) if env else None,
            stderr_cb=stderr_cb,
        )
        rpc_logger = _default_rpc_logger_factory(log_rpc_path) if log_rpc_path else None
        return cls(
            transport,
            client_name=client_name,
            client_version=client_version,
            experimental_api=experimental_api,
            approval_handler=approval_handler,
            rpc_logger=rpc_logger,
        )

    @classmethod
    def connect(
        cls,
        url: str,
        *,
        token: Optional[str] = None,
        connect_timeout: float = 30.0,
        log_rpc_path: Optional[str] = None,
        approval_handler: Optional[ApprovalHandler] = None,
        experimental_api: bool = False,
        client_name: str = "codex-control-remote",
        client_version: str = _version.__version__,
    ) -> "CodexSession":
        """Construct a session backed by a remote WebSocket transport.

        The optional :mod:`websockets` dependency is imported lazily here.
        """
        from .transport.websocket import WebSocketTransport

        transport = WebSocketTransport(
            url, token=token, connect_timeout=connect_timeout,
        )
        rpc_logger = _default_rpc_logger_factory(log_rpc_path) if log_rpc_path else None
        return cls(
            transport,
            client_name=client_name,
            client_version=client_version,
            experimental_api=experimental_api,
            approval_handler=approval_handler,
            rpc_logger=rpc_logger,
        )

    # --- lifecycle ----------------------------------------------------

    async def __aenter__(self) -> "CodexSession":
        await self.start()
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self.close()

    async def start(self) -> None:
        """Open the transport, start the reader, run the handshake."""
        if self._started:
            return
        # Start the transport.
        start = getattr(self._transport, "start", None)
        if callable(start):
            await start()
        self._reader = asyncio.create_task(self._reader_loop())
        await self._handshake()
        self._started = True

    async def close(self) -> None:
        if self._closing:
            return
        self._closing = True
        # Cancel pending requests.
        for fut in self._pending.values():
            if not fut.done():
                fut.set_exception(TransportError("session closed"))
        self._pending.clear()
        # Stop the reader, then the transport.
        if self._reader is not None:
            self._reader.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await self._reader
        with contextlib.suppress(Exception):
            await self._transport.close()
        # Close the rpc logger if it owns a file.
        log_close = getattr(self._rpc_logger, "close", None)
        if callable(log_close):  # pragma: no cover
            with contextlib.suppress(Exception):
                log_close()

    # --- low-level send/recv -----------------------------------------

    async def request(
        self,
        method: str,
        params: Optional[JsonObject] = None,
        *,
        timeout: Optional[float] = None,
    ) -> JsonObject:
        """Send a JSON-RPC request, await its result.

        Raises :class:`~codex_control.errors.RpcError` if the peer
        returned an error object; raises :class:`asyncio.TimeoutError`
        if ``timeout`` (default: ``request_timeout`` on the session) is
        exceeded.
        """
        if self._closing:
            raise TransportError("session is closing")
        mid = self._alloc_id()
        loop = asyncio.get_event_loop()
        fut: asyncio.Future[JsonObject] = loop.create_future()
        self._pending[mid] = fut
        frame = build_request(mid, method, dict(params or {}))
        await self._send(frame)
        try:
            return await asyncio.wait_for(fut, timeout=timeout or self._request_timeout)
        finally:
            self._pending.pop(mid, None)

    async def notify(self, method: str, params: Optional[JsonObject] = None) -> None:
        await self._send(build_notification(method, dict(params or {})))

    def subscribe(self, method: Optional[str] = None) -> Subscription:
        """Subscribe to notifications.

        ``method=None`` registers a wildcard subscription that receives
        every notification.
        """
        sub = Subscription(self, method)
        if method is None:
            self._wildcard_subs.append(sub)
        else:
            self._method_subs.setdefault(method, []).append(sub)
        return sub

    def _drop_subscription(self, sub: Subscription) -> None:
        if sub._method is None:
            with contextlib.suppress(ValueError):
                self._wildcard_subs.remove(sub)
        else:
            bucket = self._method_subs.get(sub._method)
            if bucket is not None:
                with contextlib.suppress(ValueError):
                    bucket.remove(sub)

    # --- high-level: handshake + threads -----------------------------

    async def _handshake(self) -> None:
        params: JsonObject = {
            "clientInfo": {
                "name": self._client_name,
                "title": self._client_title,
                "version": self._client_version,
            },
        }
        if self._experimental_api:
            params["capabilities"] = {"experimentalApi": True}
        try:
            result = await self.request(M.INITIALIZE, params, timeout=60.0)
        except Exception as exc:
            raise HandshakeError(f"initialize failed: {exc}") from exc
        self.server_info = result
        await self.notify(Notif.INITIALIZED, {})

    async def start_thread(
        self,
        *,
        cwd: Optional[str] = None,
        ephemeral: bool = True,
        sandbox: Optional[str] = None,
        approval_policy: str = "never",
        model: Optional[str] = None,
        base_instructions: Optional[str] = None,
        developer_instructions: Optional[str] = None,
        config: Optional[JsonObject] = None,
        extra: Optional[JsonObject] = None,
    ) -> "Thread":
        """Start a new thread on the server and return a :class:`Thread`.

        The kwarg names track the schema's snake_case Python equivalents
        of the camelCase wire keys. ``extra`` is the escape hatch for
        any field the schema gains after this library was written —
        contents are merged verbatim into the request params.
        """
        from .thread import Thread  # local import to break circular dep

        params: JsonObject = {
            "ephemeral": ephemeral,
            "approvalPolicy": approval_policy,
        }
        if cwd is not None:
            params["cwd"] = cwd
        if sandbox is not None:
            params["sandbox"] = sandbox
        if model is not None:
            params["model"] = model
        if base_instructions is not None:
            params["baseInstructions"] = base_instructions
        if developer_instructions is not None:
            params["developerInstructions"] = developer_instructions
        if config is not None:
            params["config"] = config
        if extra:
            params.update(extra)
        res = await self.request(M.THREAD_START, params)
        return Thread.from_start_result(self, res)

    # --- dispatch loop -----------------------------------------------

    async def _reader_loop(self) -> None:
        try:
            async for raw in self._transport:
                self._log("recv", raw)
                try:
                    frame = parse_frame(raw)
                except ProtocolError as exc:
                    log.warning("bad frame: %s; raw=%r", exc, raw)
                    continue
                if frame.kind == "request":
                    await self._handle_server_request(frame.id, frame.method, frame.params)
                elif frame.kind == "notification":
                    self._dispatch_notification(frame.method or "", frame.params)
                elif frame.kind == "response":
                    fut = self._pending.pop(frame.id, None)
                    if fut is None or fut.done():
                        log.debug("orphan response id=%r", frame.id)
                        continue
                    if frame.error is not None:
                        err = frame.error
                        fut.set_exception(
                            RpcError(
                                method="?",
                                code=int(err.get("code", -1)),
                                message=str(err.get("message", "")),
                                data=err.get("data"),
                            )
                        )
                    else:
                        fut.set_result(frame.result if frame.result is not None else {})
                else:
                    log.debug("dropping unknown frame: %r", raw)
        except asyncio.CancelledError:  # pragma: no cover
            raise
        except Exception as exc:  # pragma: no cover
            log.exception("reader loop terminated: %s", exc)
            self._fail_pending(exc)

    async def _handle_server_request(
        self, mid: Any, method: Optional[str], params: JsonObject
    ) -> None:
        decision: Any = {"decision": "decline"}
        if self._approval_handler is not None:
            try:
                raw_decision = self._approval_handler(method or "", params)
            except Exception as exc:
                log.exception("approval handler raised: %s", exc)
                raw_decision = {"decision": "decline", "_handler_error": str(exc)}
            decision = (
                {"decision": raw_decision}
                if isinstance(raw_decision, str)
                else raw_decision
            )
        # Older surfaces use ``"approved"``.
        if method in (ServerReq.EXEC_COMMAND_APPROVAL, ServerReq.APPLY_PATCH_APPROVAL):
            decision.setdefault("decision", "approved")
        await self._send(build_response(mid, decision))

    def _dispatch_notification(self, method: str, params: JsonObject) -> None:
        payload: JsonObject = {"method": method, "params": params}
        for sub in self._method_subs.get(method, ()):
            sub._put_nowait(payload)
        for sub in self._wildcard_subs:
            sub._put_nowait(payload)

    # --- internal helpers --------------------------------------------

    def _alloc_id(self) -> int:
        self._next_id += 1
        return self._next_id

    async def _send(self, frame: JsonObject) -> None:
        self._log("send", frame)
        await self._transport.send(frame)

    def _log(self, direction: str, frame: JsonObject) -> None:
        if self._rpc_logger is not None:
            with contextlib.suppress(Exception):
                self._rpc_logger(direction, frame)

    def _fail_pending(self, exc: BaseException) -> None:
        for fut in self._pending.values():
            if not fut.done():
                fut.set_exception(
                    TransportError(f"transport closed: {exc}")
                )
        self._pending.clear()

    # --- introspection ------------------------------------------------

    @property
    def pid(self) -> Optional[int]:
        return getattr(self._transport, "pid", None)
