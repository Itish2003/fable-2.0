"""Normalizes a DATABASE_URL for asyncpg.

Neon (and other managed Postgres providers) hand out connection strings
with libpq-style query params -- sslmode=require, channel_binding=require
-- that asyncpg's connect() doesn't accept as keyword arguments (it raises
TypeError: connect() got an unexpected keyword argument 'sslmode'). Strip
those from the URL and translate sslmode into the connect_args SQLAlchemy's
asyncpg dialect actually understands. Local dev URLs with no query string
pass through unchanged (connect_args stays empty, matching prior behavior).

Shared by src/database.py (our own engine) and src/services/session_manager
.py (ADK's DatabaseSessionService, which forwards **kwargs -- including
connect_args -- straight into its own create_async_engine call).
"""

from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


def normalize_db_url(raw_url: str) -> tuple[str, dict]:
    parts = urlsplit(raw_url)
    query_pairs = dict(parse_qsl(parts.query))
    sslmode = query_pairs.pop("sslmode", None)
    # channel_binding is a libpq TLS-channel-binding hint; asyncpg doesn't
    # take it as a kwarg, and ssl="require" below already covers the actual
    # TLS requirement, so it's safe to just drop.
    query_pairs.pop("channel_binding", None)

    # Neon (and other providers) hand out a bare "postgresql://" scheme.
    # Without an explicit driver, SQLAlchemy picks whichever sync/psycopg
    # dialect is installed rather than asyncpg -- this project's engines are
    # all async, so force the driver rather than let install order decide.
    scheme = parts.scheme
    if scheme in ("postgresql", "postgres"):
        scheme = "postgresql+asyncpg"

    clean_url = urlunsplit((scheme, parts.netloc, parts.path, urlencode(query_pairs), parts.fragment))
    connect_args = {"ssl": "require"} if sslmode else {}
    return clean_url, connect_args


def bare_asyncpg_dsn(raw_url: str) -> tuple[str, dict]:
    """Same normalization, but for raw `asyncpg.connect()`/`create_pool()`
    calls (spend_guard.py, ws/notify_bridge.py) rather than SQLAlchemy --
    those want a bare "postgresql://" DSN; asyncpg's own connect() doesn't
    understand a "+asyncpg" (or any "+driver") suffix, and callers here may
    well be reusing this project's own DATABASE_URL, which carries that
    suffix for SQLAlchemy's benefit (src/database.py) -- so strip it, not
    just normalize a bare "postgres"/"postgresql" scheme."""
    parts = urlsplit(raw_url)
    query_pairs = dict(parse_qsl(parts.query))
    sslmode = query_pairs.pop("sslmode", None)
    scheme = parts.scheme.split("+", 1)[0]
    if scheme not in ("postgresql", "postgres"):
        scheme = "postgresql"
    dsn = f"{scheme}://{parts.netloc}{parts.path}"
    connect_kwargs = {"ssl": "require"} if sslmode else {}
    return dsn, connect_kwargs
