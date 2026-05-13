"""Tiny logging helper.

Most users never call this; if you want structured output for a run,
:func:`configure_logging` sets up a stderr handler with a stable
format. Production embedders should configure their own ``logging``
root and skip this entirely.
"""

from __future__ import annotations

import logging
import os


def configure_logging(level: int | str = logging.INFO) -> None:
    """Add a stderr handler to the root logger if none is configured.

    Idempotent. Honours the ``CODEX_CONTROL_LOG_LEVEL`` env var, which
    overrides the ``level`` argument when set.
    """
    env_level = os.environ.get("CODEX_CONTROL_LOG_LEVEL")
    if env_level:
        level = env_level
    root = logging.getLogger()
    if not any(isinstance(h, logging.StreamHandler) for h in root.handlers):
        handler = logging.StreamHandler()
        handler.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)-5s %(name)s: %(message)s")
        )
        root.addHandler(handler)
    root.setLevel(level)
