""":class:`McpToolResult` — typed view of one ``mcpServer/tool/call`` reply.

The MCP spec frames a tool's return value as a list of *content
blocks*. Each block carries its own ``type`` discriminator
(``"text" | "image" | "resource"``, with more coming in future spec
revisions). Walking that list to pull out the bits a caller wants is
the same six lines repeated everywhere — and it is exactly the lines
that change when the spec adds a discriminator value. Putting the
walking here, behind a typed accessor surface, quarantines the churn
to one file when the MCP spec evolves and leaves callers
unaffected.

Construction is private. Public callers reach a ``McpToolResult`` by
invoking :meth:`codex_control.plugins.Plugins.call_tool` (or, when
that lands as sugar on the session, ``session.mcp_tool_call(...)``).
The class is exported so callers have a name for the return type;
the helper that builds it is not.
"""
from __future__ import annotations

import base64
import copy
import json
from typing import Any, Iterable, Mapping


class McpToolResult:
    """One ``tools/call`` result, with typed accessors over content blocks.

    ``raw`` is the unmodified server reply. The accessor methods
    (:meth:`text`, :meth:`image_bytes`, :meth:`json`,
    :meth:`resource_blob`) walk ``raw["content"]`` and pluck out the
    first matching block. They never raise on a missing block; they
    return ``None`` (or ``""`` for :meth:`text`). Strict callers can
    inspect ``raw`` directly.
    """

    __slots__ = ("_raw",)

    def __init__(self, raw: Mapping[str, Any]) -> None:
        # Defensive deep copy: the content list lives one level inside
        # the dict and tests rely on the result being invariant to
        # post-construction mutation of the source.
        self._raw: dict[str, Any] = copy.deepcopy(dict(raw))

    # --- inspectors ---------------------------------------------------

    @property
    def raw(self) -> Mapping[str, Any]:
        return self._raw

    @property
    def is_error(self) -> bool:
        return bool(self._raw.get("isError"))

    def _blocks(self) -> Iterable[Mapping[str, Any]]:
        for block in self._raw.get("content", []) or []:
            if isinstance(block, Mapping):
                yield block

    # --- typed extractors --------------------------------------------

    def text(self, *, joiner: str = "\n") -> str:
        """All ``text`` blocks joined by ``joiner``. Empty string if none.

        We deliberately *concat* rather than return the first hit: the
        macOS computer-use plugin's ``get_app_state`` returns the
        accessibility-tree JSON in one text block and the screenshot in
        a separate image block; future tools may split text across
        multiple blocks, and reassembly is the obvious behaviour.
        """
        return joiner.join(
            b.get("text", "") for b in self._blocks() if b.get("type") == "text"
        )

    def image_bytes(self) -> bytes | None:
        """First image block, base64-decoded. ``None`` if none present.

        Handles two shapes the spec admits today:
          - ``{"type": "image", "data": "<base64>", "mimeType": "..."}``
          - ``{"type": "resource", "resource": {"blob": "<base64>"}}``
        """
        for b in self._blocks():
            t = b.get("type")
            if t == "image":
                data = b.get("data")
                if isinstance(data, str):
                    return base64.b64decode(data)
            elif t == "resource":
                resource = b.get("resource")
                if isinstance(resource, Mapping):
                    blob = resource.get("blob")
                    if isinstance(blob, str):
                        return base64.b64decode(blob)
        return None

    def json(self) -> Any:
        """Parse the joined text as JSON, or ``None`` if it doesn't parse.

        Useful for tools whose contract is "the meaningful return is
        JSON in a text block" (``list_apps``, ``get_app_state``).
        """
        text = self.text()
        if not text:
            return None
        try:
            return json.loads(text)
        except (ValueError, TypeError):
            return None

    def resource_blob(self, *, uri_prefix: str | None = None) -> bytes | None:
        """First ``resource`` block, optionally filtered by URI prefix."""
        for b in self._blocks():
            if b.get("type") != "resource":
                continue
            resource = b.get("resource") or {}
            if uri_prefix and not str(resource.get("uri", "")).startswith(uri_prefix):
                continue
            blob = resource.get("blob")
            if isinstance(blob, str):
                return base64.b64decode(blob)
        return None

    # --- presentation -------------------------------------------------

    def __repr__(self) -> str:
        block_types = [b.get("type") for b in self._blocks()]
        return (
            f"McpToolResult(is_error={self.is_error}, "
            f"blocks={block_types})"
        )
