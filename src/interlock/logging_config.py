"""v2.8.1 — backend logging setup.

Default level: INFO. Override via ``INTERLOCK_LOG_LEVEL`` env var
(``DEBUG``, ``INFO``, ``WARNING``, ``ERROR``). Streamlit hides our log
output by default; calling ``configure_logging()`` at app startup sets
up a stderr handler with a uniform format so every log line is
greppable and carries a module tag.

The configuration is idempotent — repeat calls don't add duplicate
handlers (matters because Streamlit reruns the script on every
interaction).

Log layout::

    2026-05-23 14:30:01,234 INFO interlock.pipeline: vision-lane stage START doc_a=...
    └─ timestamp ──────────┘ level └─ logger name ──────┘ message

Module-level loggers (``logger = logging.getLogger(__name__)``) inherit
this configuration automatically.
"""

from __future__ import annotations

import logging
import os
import sys

_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"
_DATEFMT = "%Y-%m-%d %H:%M:%S"
_INSTALLED_FLAG = "_interlock_logging_installed"


def configure_logging(level: str | int | None = None) -> None:
    """Idempotently install a stderr handler for the ``interlock.*``
    logger tree. Default level: env ``INTERLOCK_LOG_LEVEL`` or ``INFO``.
    """
    root = logging.getLogger("interlock")
    if getattr(root, _INSTALLED_FLAG, False):
        # Already configured this process. Allow level to be raised /
        # lowered on subsequent calls but do not stack handlers.
        if level is not None:
            root.setLevel(_resolve_level(level))
        return

    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(logging.Formatter(_FORMAT, datefmt=_DATEFMT))
    root.addHandler(handler)
    root.setLevel(_resolve_level(level))
    root.propagate = False  # don't double-emit via the root logger
    setattr(root, _INSTALLED_FLAG, True)


def _resolve_level(level: str | int | None) -> int:
    if level is None:
        level = os.environ.get("INTERLOCK_LOG_LEVEL", "INFO")
    if isinstance(level, int):
        return level
    return logging.getLevelName(str(level).upper())  # type: ignore[no-any-return]
