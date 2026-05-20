"""Project-root pytest config: ensure .env always wins over shell env.

Claude Code (and some shells) export ``ANTHROPIC_API_KEY=`` as an empty
string, which blocks ``load_dotenv()``'s default (no-override) from picking
up the real key from .env. Forcing ``override=True`` at collection time
makes the project's own .env authoritative regardless of how the shell is
set up.
"""

from __future__ import annotations

from dotenv import load_dotenv

load_dotenv(override=True)
