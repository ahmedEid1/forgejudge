"""Shared pytest fixtures and path setup for the ForgeJudge test suite."""

import os
import sys
from pathlib import Path

# Ensure the repo root is importable when tests run from any cwd.
REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

# Hosts that are never safe to TRUNCATE: anything that is not the local
# disposable pgvector container. The leaderboard's public Neon DB lives on
# *.neon.tech, but we deny *every* non-local host to fail safe.
_LOCAL_HOSTS = ("localhost", "127.0.0.1", "::1", "[::1]")


def _is_local_dsn(dsn: str) -> bool:
    """True only if ``dsn`` points at a local (loopback) Postgres host.

    Destructive DB tests TRUNCATE; they must run ONLY against the disposable
    local container, never the production Neon leaderboard DB.
    """
    low = dsn.lower()
    if "neon.tech" in low:
        return False
    # Extract the host between '@' and the next ':' / '/' / end.
    host = low
    if "@" in host:
        host = host.split("@", 1)[1]
    # strip credentials-less ('postgresql://host...') leading scheme too
    elif "://" in host:
        host = host.split("://", 1)[1]
    for sep in ("/", "?"):
        if sep in host:
            host = host.split(sep, 1)[0]
    # host may still carry ':port'
    if host.startswith("[") and "]" in host:  # IPv6 literal e.g. [::1]:5432
        host = host[: host.index("]") + 1]
    else:
        host = host.split(":", 1)[0]
    return host in _LOCAL_HOSTS


def local_db_dsn() -> str | None:
    """Return the disposable LOCAL test DSN, or ``None`` if not safely set.

    SAFETY: reads ONLY ``FJ_LOCAL_DATABASE_URL`` — it intentionally NEVER falls
    back to ``DATABASE_URL`` (the production Neon leaderboard DB), so destructive
    fixtures can never TRUNCATE production. Returns ``None`` when the var is
    unset/empty OR points at a non-local host; callers must ``pytest.skip()``.
    """
    dsn = os.getenv("FJ_LOCAL_DATABASE_URL")
    if not dsn:
        return None
    if not _is_local_dsn(dsn):
        return None
    return dsn
