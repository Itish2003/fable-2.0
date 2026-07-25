"""Cross-instance liveness bridge for the live demo (2026-07-25).

Why this exists: on Vercel, the WS connection manager (src/ws/manager.py)
holds sockets in per-instance memory, and a demo tool's engine action
(src/demo_tools.py, invoked from the in-process A2A agent) may run on a
DIFFERENT Fluid Compute instance than the one holding the visitor's iframe
socket -- there's no shared memory between them. Postgres NOTIFY/LISTEN
closes the gap: after any state-mutating engine action, NOTIFY a channel
with just "<session_id>:<kind>" (a doorbell, never chapter prose -- NOTIFY
payloads cap at 8KB and this project's chapters can exceed that easily).
Every instance currently holding at least one socket runs ONE LISTEN
connection; on a notification for a session it holds, it re-derives what to
push from Postgres via ws.runner.emit_resume_snapshot -- the exact same
rebuild the WS-connect resume path already uses, so there's no new
push-payload logic to get wrong, just a new trigger for existing logic.

LISTEN needs the DIRECT (unpooled) connection, not pgbouncer: transaction
pooling can hand the physical backend that issued LISTEN to a different
client between notifications, silently dropping delivery. fable's own
DATABASE_URL is already Neon's direct endpoint (src/database.py), so this
reuses that same env var rather than needing another connection string.
"""

import asyncio
import logging
import os

import asyncpg

from src.db_url import bare_asyncpg_dsn

logger = logging.getLogger("fable.notify_bridge")

CHANNEL = "fable_ws"

_listener_started = False
_listener_lock = asyncio.Lock()


async def ensure_listener_started() -> None:
    """Start this instance's single LISTEN connection, once, on first
    socket connect (src/ws/manager.py calls this from connect())."""
    global _listener_started
    if _listener_started:
        return
    async with _listener_lock:
        if _listener_started:
            return
        _listener_started = True
        asyncio.create_task(_run_listener())


async def _run_listener() -> None:
    try:
        dsn, connect_kwargs = bare_asyncpg_dsn(os.environ["DATABASE_URL"])
        conn = await asyncpg.connect(dsn, **connect_kwargs)
    except Exception:
        logger.exception("notify_bridge: failed to open LISTEN connection")
        global _listener_started
        _listener_started = False  # let a later connect() retry
        return

    async def _on_notify(_connection, _pid, _channel, payload: str) -> None:
        asyncio.create_task(_handle_notify(payload))

    try:
        await conn.add_listener(CHANNEL, _on_notify)
        logger.info("notify_bridge: LISTEN %s started", CHANNEL)
        # Keep this connection (and this task) alive for the instance's
        # lifetime -- add_listener's callback fires on the connection's own
        # event-loop machinery, this loop just holds the connection open.
        while True:
            await asyncio.sleep(3600)
    except asyncio.CancelledError:
        raise
    except Exception:
        logger.exception("notify_bridge: LISTEN connection failed")
    finally:
        await conn.close()


async def _handle_notify(payload: str) -> None:
    # Deferred import: ws.runner also imports this module (to call
    # notify_change at the end of execute_adk_turn) -- importing at module
    # load time here would be circular.
    from src.ws.manager import manager
    from src.ws.runner import emit_resume_snapshot

    try:
        session_id, kind = payload.split(":", 1)
    except ValueError:
        logger.warning("notify_bridge: malformed payload %r", payload)
        return

    if session_id not in manager.active_connections:
        return  # not held on this instance -- nothing to do

    logger.info("notify_bridge: re-emitting session %s (kind=%s) on this instance", session_id, kind)
    try:
        await emit_resume_snapshot(session_id)
    except Exception:
        logger.exception("notify_bridge: re-emit failed for session %s", session_id)


async def notify_change(session_id: str, kind: str) -> None:
    """Fire-and-forget NOTIFY via a short-lived direct connection. Never
    let a ledger/DB hiccup here break the caller's actual state mutation --
    the mutation already happened; this is best-effort liveness only."""
    try:
        dsn, connect_kwargs = bare_asyncpg_dsn(os.environ["DATABASE_URL"])
        conn = await asyncpg.connect(dsn, **connect_kwargs)
        try:
            payload = f"{session_id}:{kind}"
            await conn.execute("SELECT pg_notify($1, $2)", CHANNEL, payload)
        finally:
            await conn.close()
    except Exception:
        logger.warning("notify_bridge: NOTIFY failed for session %s (kind=%s)", session_id, kind, exc_info=True)
