"""Demo write-tools for the live A2A choreography ("Option A", 2026-07-25).

The agent performs real engine actions (create/advance/rewind a story
session) and the visitor's /demo/ iframe is a live window onto them --
these tools are what makes that real rather than narrated. All three call
straight into the engine in-process (session_manager, execute_adk_turn,
fable_runner.rewind_async) -- no HTTP hop, same in-process pattern as
a2a_agent.py's own ENGINE_TRANSPORT=asgi grounding tools.

Session pointer contract (pinned by team-lead, portfolio's LeafPane
depends on it): every successful call returns a dict that a2a_agent.py's
a2a_send_message turns into an EXTRA reply part -- mediaType
application/x-portfolio-live-session+json, JSON
{"sessionId", "url", "note"}.

Constraints:
- user_id is ALWAYS "local_tester" -- src/main.py's story_websocket
  hardcodes that user_id in its own session lookup, so a session created
  under any other user_id would connect the visitor's /demo/ iframe to a
  socket that always 404s with session_not_found. Not a choice made here;
  a property of the existing WS handler.
- DEMO_MAX_ENGINE_TURNS_PER_CONTEXT (env, default 3): each "engine turn"
  is several real model calls (storyteller/auditor/archivist), not one --
  capped per A2A contextId (the whole visitor conversation), not per chat
  message, so a chatty visitor can't multiply spend by asking the same
  demo to advance many times. Tracked in-memory (module-level dict keyed
  by contextId) -- same instance-local caveat as a2a_agent.py's
  CONTEXT_HISTORY; a cold start resets the count, which is the
  conservative failure direction (undercounts, never wrongly blocks a
  legitimate new instance).
"""

import logging
import os
from contextvars import ContextVar
from typing import Any

from sqlalchemy import text as sql_text

from src.app_container import fable_runner
from src.database import engine as _engine
from src.services.session_manager import create_fable_session
from src.ws.runner import execute_adk_turn, find_pending_interrupt

logger = logging.getLogger("fable.demo_tools")

DEMO_USER_ID = "local_tester"  # see module docstring -- not configurable
MAX_ENGINE_TURNS_PER_CONTEXT = int(os.getenv("DEMO_MAX_ENGINE_TURNS_PER_CONTEXT", "3"))

# Set by a2a_agent.py's a2a_send_message at the top of each request, read
# by the tools below -- avoids threading contextId through every TOOL_IMPLS
# signature just for these three tools.
A2A_CONTEXT_ID: ContextVar[str | None] = ContextVar("A2A_CONTEXT_ID", default=None)
# Set by whichever tool ran during this turn; a2a_send_message reads it
# after run_agent_turn returns to attach the session-pointer reply part.
DEMO_POINTER: ContextVar[dict | None] = ContextVar("DEMO_POINTER", default=None)

_ENGINE_TURN_COUNTS: dict[str, int] = {}
_CURRENT_DEMO_SESSION: dict[str, str] = {}  # a2a contextId -> most recent demo session_id


def _demo_url(session_id: str) -> str:
    base = os.getenv("A2A_BASE_URL", "http://localhost:8001")
    return f"{base}/demo/?session={session_id}"


def _check_and_consume_turn_budget() -> str | None:
    """Returns an error string if the per-contextId engine-turn cap is
    already hit; otherwise increments the count and returns None."""
    context_id = A2A_CONTEXT_ID.get()
    if context_id is None:
        return None  # no contextId to key on -- shouldn't happen via a2a_agent.py, don't block
    count = _ENGINE_TURN_COUNTS.get(context_id, 0)
    if count >= MAX_ENGINE_TURNS_PER_CONTEXT:
        return (
            f"This demo has already used its {MAX_ENGINE_TURNS_PER_CONTEXT} engine turns for "
            "this conversation -- each one is a real, metered model call. Start a new "
            "conversation to try again."
        )
    _ENGINE_TURN_COUNTS[context_id] = count + 1
    return None


async def _fetch_session(session_id: str):
    return await fable_runner.session_service.get_session(
        app_name=fable_runner.app_name,
        user_id=DEMO_USER_ID,
        session_id=session_id,
    )


def _set_pointer(session_id: str, note: str) -> dict:
    pointer = {"sessionId": session_id, "url": _demo_url(session_id), "note": note}
    DEMO_POINTER.set(pointer)
    return pointer


async def _describe_state(session_id: str) -> str:
    """Short human-readable label for what the session is doing right now,
    for the pointer's `note` field -- same pending-interrupt / chapter-meta
    lookup emit_resume_snapshot uses to decide what to push, just rendered
    as text instead of WS frames."""
    existing = await _fetch_session(session_id)
    if existing is None:
        return "session not found"
    state = existing.state or {}
    interrupt_id, message = find_pending_interrupt(existing)
    if interrupt_id:
        return f"awaiting setup input ({interrupt_id}): {message}"[:200]
    chapter = int(state.get("chapter_count", 1) or 1)
    chap_meta = state.get("last_chapter_meta")
    if chap_meta:
        summary = chap_meta.get("summary") or "no summary"
        return f"watching chapter {chapter} — {summary}"[:200]
    return f"chapter {chapter} in progress"


async def start_demo_story(args: dict[str, Any]) -> dict[str, Any]:
    del args  # no parameters -- the premise comes via a follow-up advance_demo_story call
    budget_error = _check_and_consume_turn_budget()
    if budget_error:
        return {"ok": False, "error": budget_error}

    session_id = await create_fable_session(user_id=DEMO_USER_ID)
    context_id = A2A_CONTEXT_ID.get()
    if context_id:
        _CURRENT_DEMO_SESSION[context_id] = session_id

    try:
        await execute_adk_turn(session_id=session_id, user_id=DEMO_USER_ID, message_text="/start")
    except Exception as e:
        logger.exception("start_demo_story: initial turn failed for %s", session_id)
        return {"ok": False, "error": f"engine turn failed: {e}"}

    note = f"story created — {await _describe_state(session_id)}"
    return {"ok": True, **_set_pointer(session_id, note)}


async def advance_demo_story(args: dict[str, Any]) -> dict[str, Any]:
    context_id = A2A_CONTEXT_ID.get()
    session_id = args.get("session_id") or _CURRENT_DEMO_SESSION.get(context_id or "")
    input_text = (args.get("input") or "").strip()
    if not session_id:
        return {"ok": False, "error": "no session_id given and no demo story started yet in this conversation"}
    if not input_text:
        return {"ok": False, "error": "input text is required"}

    budget_error = _check_and_consume_turn_budget()
    if budget_error:
        return {"ok": False, "error": budget_error}

    existing = await _fetch_session(session_id)
    if existing is None:
        return {"ok": False, "error": f"session {session_id} not found"}

    interrupt_id, _ = find_pending_interrupt(existing)
    try:
        if interrupt_id:
            await execute_adk_turn(
                session_id=session_id, user_id=DEMO_USER_ID,
                resume_payload=input_text, interrupt_id=interrupt_id,
            )
        else:
            await execute_adk_turn(session_id=session_id, user_id=DEMO_USER_ID, message_text=input_text)
    except Exception as e:
        logger.exception("advance_demo_story: turn failed for %s", session_id)
        return {"ok": False, "error": f"engine turn failed: {e}"}

    note = f"advanced — {await _describe_state(session_id)}"
    return {"ok": True, **_set_pointer(session_id, note)}


async def rewind_demo_story(args: dict[str, Any]) -> dict[str, Any]:
    context_id = A2A_CONTEXT_ID.get()
    session_id = args.get("session_id") or _CURRENT_DEMO_SESSION.get(context_id or "")
    if not session_id:
        return {"ok": False, "error": "no session_id given and no demo story started yet in this conversation"}

    budget_error = _check_and_consume_turn_budget()
    if budget_error:
        return {"ok": False, "error": budget_error}

    # Rewind before the most recent invocation -- matches the UI's "Undo"
    # button semantics, no invocation_id needed from the caller.
    try:
        async with _engine.connect() as db:
            row = (await db.execute(sql_text(
                """SELECT invocation_id FROM events
                   WHERE session_id = :sid AND invocation_id IS NOT NULL AND invocation_id != ''
                   ORDER BY timestamp DESC LIMIT 1"""
            ), {"sid": session_id})).first()
    except Exception as e:
        logger.exception("rewind_demo_story: invocation lookup failed for %s", session_id)
        return {"ok": False, "error": f"could not find a turn to rewind: {e}"}

    if not row or not row[0]:
        return {"ok": False, "error": "nothing to rewind yet"}

    try:
        await fable_runner.rewind_async(
            user_id=DEMO_USER_ID, session_id=session_id, rewind_before_invocation_id=row[0],
        )
    except Exception as e:
        logger.exception("rewind_demo_story: rewind failed for %s", session_id)
        return {"ok": False, "error": f"rewind failed: {e}"}

    # rewind_async doesn't route through execute_adk_turn (which normally
    # fires the NOTIFY at turn-completion), so fire it explicitly here.
    from src.ws.notify_bridge import notify_change
    await notify_change(session_id, "rewind")

    note = f"rewound — {await _describe_state(session_id)}"
    return {"ok": True, **_set_pointer(session_id, note)}
