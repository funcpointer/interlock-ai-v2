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

    Re-reads the env var on every call (Streamlit reruns the script on
    every interaction; without this, an .env update wouldn't apply until
    a full process restart).
    """
    root = logging.getLogger("interlock")
    resolved = _resolve_level(level)

    if getattr(root, _INSTALLED_FLAG, False):
        # Don't stack handlers, but DO re-apply level so env-var edits
        # take effect on Streamlit reruns.
        if root.level != resolved:
            root.setLevel(resolved)
            root.info(
                "interlock logging level refreshed to %s (was %s)",
                logging.getLevelName(resolved),
                logging.getLevelName(root.level),
            )
        return

    handler = logging.StreamHandler(sys.stderr)
    handler.setLevel(logging.DEBUG)  # handler accepts everything; logger filters
    handler.setFormatter(logging.Formatter(_FORMAT, datefmt=_DATEFMT))
    root.addHandler(handler)
    root.setLevel(resolved)
    root.propagate = False  # don't double-emit via the root logger
    setattr(root, _INSTALLED_FLAG, True)
    # Visible confirmation so triage can SEE the configured level.
    # Logged at WARNING so it shows even when level is WARNING.
    src = (
        f"arg={level!r}" if level is not None
        else f"env INTERLOCK_LOG_LEVEL={os.environ.get('INTERLOCK_LOG_LEVEL', '(unset)')!r}"
    )
    root.warning(
        "interlock logging configured: level=%s (%s)",
        logging.getLevelName(resolved), src,
    )


def _resolve_level(level: str | int | None) -> int:
    if level is None:
        level = os.environ.get("INTERLOCK_LOG_LEVEL", "INFO")
    if isinstance(level, int):
        return level
    return logging.getLevelName(str(level).upper())  # type: ignore[no-any-return]
