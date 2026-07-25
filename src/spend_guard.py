"""Anti-abuse spend controls for fable-2.0's public /a2a, ported from the
portfolio's agent/lib/spend-guard.ts (and the rac agent's a2a.ts wiring of
it) so all three A2A origins share one wallet against the single DeepSeek
key.

Shares the SAME spend_ledger table in the portfolio's memory Postgres
(Neon) -- NOT fable's own engine database. This module never authenticates
anything; it only decides pass/block for a turn (check_spend) and records
provider-reported usage after the fact (record_usage). Fails OPEN on ledger
infra errors (a dead ledger must not take the agent down), fails CLOSED
(403) on an actual ceiling breach.

Connection note: MEMORY_DATABASE_URL is Neon's POOLED (pgbouncer) endpoint,
not a pgvector database -- plain asyncpg with statement_cache_size=0,
verified against a real query (2026-07-25), since pgbouncer's transaction
pooling can hand a prepared statement to a different physical backend than
the one that prepared it.
"""

import logging
import os
from typing import NamedTuple
from urllib.parse import parse_qsl, urlsplit

import asyncpg

logger = logging.getLogger("fable.spend_guard")

CEILINGS = {
    "sessions_per_ip": int(os.getenv("SPEND_MAX_SESSIONS_PER_IP", "20")),
    "sessions_global": int(os.getenv("SPEND_MAX_SESSIONS", "300")),
    "input_tokens_global": int(os.getenv("SPEND_MAX_INPUT_TOKENS", "20000000")),
    "output_tokens_global": int(os.getenv("SPEND_MAX_OUTPUT_TOKENS", "2000000")),
}

_pool: asyncpg.Pool | None = None
_schema_ready = False


def _ledger_dsn() -> tuple[str, dict]:
    raw = os.environ["MEMORY_DATABASE_URL"]
    parts = urlsplit(raw)
    query = dict(parse_qsl(parts.query))
    ssl = "require" if query.get("sslmode") else None
    scheme = "postgresql" if parts.scheme in ("postgresql", "postgres") else parts.scheme
    dsn = f"{scheme}://{parts.netloc}{parts.path}"
    connect_kwargs: dict = {"statement_cache_size": 0}
    if ssl:
        connect_kwargs["ssl"] = ssl
    return dsn, connect_kwargs


async def _get_pool() -> asyncpg.Pool:
    global _pool, _schema_ready
    if _pool is None:
        dsn, connect_kwargs = _ledger_dsn()
        _pool = await asyncpg.create_pool(dsn, min_size=0, max_size=2, **connect_kwargs)
    if not _schema_ready:
        async with _pool.acquire() as conn:
            await conn.execute(
                """CREATE TABLE IF NOT EXISTS spend_ledger (
                     day DATE NOT NULL,
                     ip TEXT NOT NULL,
                     sessions INT NOT NULL DEFAULT 0,
                     input_tokens BIGINT NOT NULL DEFAULT 0,
                     output_tokens BIGINT NOT NULL DEFAULT 0,
                     PRIMARY KEY (day, ip)
                   )"""
            )
        _schema_ready = True
    return _pool


def client_ip(headers) -> str:
    """headers: a Starlette/FastAPI Headers-like mapping (case-insensitive .get)."""
    xff = headers.get("x-forwarded-for")
    if xff:
        return xff.split(",")[0].strip()
    return headers.get("x-real-ip") or "local"


class SpendVerdict(NamedTuple):
    allowed: bool
    reason: str | None = None


async def check_spend(ip: str, new_session: bool) -> SpendVerdict:
    """Raises on ledger infra errors -- caller decides fail-open."""
    pool = await _get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """SELECT
                 COALESCE(SUM(input_tokens), 0) AS input_tokens,
                 COALESCE(SUM(output_tokens), 0) AS output_tokens,
                 COALESCE(SUM(sessions), 0) AS sessions,
                 COALESCE(SUM(sessions) FILTER (WHERE ip = $1), 0) AS ip_sessions
               FROM spend_ledger WHERE day = CURRENT_DATE""",
            ip,
        )
        if row["input_tokens"] >= CEILINGS["input_tokens_global"]:
            return SpendVerdict(False, "daily input-token ceiling reached")
        if row["output_tokens"] >= CEILINGS["output_tokens_global"]:
            return SpendVerdict(False, "daily output-token ceiling reached")
        if new_session:
            if row["sessions"] >= CEILINGS["sessions_global"]:
                return SpendVerdict(False, "daily session ceiling reached")
            if row["ip_sessions"] >= CEILINGS["sessions_per_ip"]:
                return SpendVerdict(False, "daily per-visitor session cap reached")
            await conn.execute(
                """INSERT INTO spend_ledger (day, ip, sessions) VALUES (CURRENT_DATE, $1, 1)
                   ON CONFLICT (day, ip) DO UPDATE SET sessions = spend_ledger.sessions + 1""",
                ip,
            )
    return SpendVerdict(True)


async def record_usage(input_tokens: int, output_tokens: int, ip: str = "_usage") -> None:
    if input_tokens == 0 and output_tokens == 0:
        return
    pool = await _get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """INSERT INTO spend_ledger (day, ip, input_tokens, output_tokens)
               VALUES (CURRENT_DATE, $1, $2, $3)
               ON CONFLICT (day, ip) DO UPDATE SET
                 input_tokens = spend_ledger.input_tokens + EXCLUDED.input_tokens,
                 output_tokens = spend_ledger.output_tokens + EXCLUDED.output_tokens""",
            ip,
            input_tokens,
            output_tokens,
        )
