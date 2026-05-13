"""Capability introspection.

A "dossier" of what the live Codex binary supports: models, modes,
experimental features, model-provider capabilities, registered apps.
Useful as a smoke check after bumping Codex, and as a sanity check at
the start of a training run.

All calls are read-only. Each helper returns either the unwrapped
``data`` list (for ``*/list`` endpoints) or the raw response payload.
Failures are caught and returned as ``None`` so a missing experimental
endpoint doesn't blow up the whole dossier.
"""

from __future__ import annotations

import dataclasses
import logging
from typing import Any, TYPE_CHECKING

from .errors import CodexControlError
from .protocol.methods import M

if TYPE_CHECKING:
    from .session import CodexSession

log = logging.getLogger(__name__)


@dataclasses.dataclass
class CapabilityDossier:
    """Read-only snapshot of the server's introspectable capabilities."""

    server_info: dict[str, Any]
    models: list[dict[str, Any]] | None
    collaboration_modes: list[dict[str, Any]] | None
    experimental_features: list[dict[str, Any]] | None
    model_provider_capabilities: dict[str, Any] | None
    apps: list[dict[str, Any]] | None
    errors: dict[str, str]


async def _safe_list(
    session: "CodexSession", method: str, params: dict[str, Any] | None = None
) -> tuple[list[dict[str, Any]] | None, str | None]:
    try:
        res = await session.request(method, params or {})
    except CodexControlError as exc:
        return None, str(exc)
    data = res.get("data")
    if isinstance(data, list):
        return data, None
    # Some endpoints don't follow the {data: [...]} shape; surface raw.
    return [res], None


async def fetch_dossier(session: "CodexSession") -> CapabilityDossier:
    """Pull a full capability dossier from the connected app-server.

    Pass ``experimental_api=True`` to :func:`CodexSession.spawn` /
    :func:`CodexSession.connect` if you want the experimental-feature
    list to come back populated; without that capability the server
    returns ``Method not found`` for ``experimentalFeature/list`` and
    that's recorded in ``errors``.
    """
    errors: dict[str, str] = {}

    models, err = await _safe_list(session, M.MODEL_LIST, {"includeHidden": False})
    if err:
        errors[M.MODEL_LIST] = err

    modes, err = await _safe_list(session, M.COLLABORATION_MODE_LIST)
    if err:
        errors[M.COLLABORATION_MODE_LIST] = err

    feats, err = await _safe_list(session, M.EXPERIMENTAL_FEATURE_LIST)
    if err:
        errors[M.EXPERIMENTAL_FEATURE_LIST] = err

    try:
        mp_caps = await session.request(M.MODEL_PROVIDER_CAPABILITIES_READ, {})
    except CodexControlError as exc:
        mp_caps = None
        errors[M.MODEL_PROVIDER_CAPABILITIES_READ] = str(exc)

    apps, err = await _safe_list(session, M.APP_LIST)
    if err:
        errors[M.APP_LIST] = err

    return CapabilityDossier(
        server_info=dict(session.server_info or {}),
        models=models,
        collaboration_modes=modes,
        experimental_features=feats,
        model_provider_capabilities=mp_caps,
        apps=apps,
        errors=errors,
    )
