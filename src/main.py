import asyncio
import logging
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from src.database import init_db
from src.ws.manager import manager
from src.ws.runner import execute_adk_turn
from src.a2a_agent import router as a2a_router

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("fable.main")

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifecycle events for FastAPI."""
    logger.info("Initializing Fable 2.0 Database Schema...")
    await init_db()
    yield
    logger.info("Fable 2.0 Server shutting down...")

app = FastAPI(
    title="Fable 2.0 ADK Engine",
    description="Graph-based narrative simulation engine.",
    version="2.0.0",
    lifespan=lifespan
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], # For local testing
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# fable-2.0's real A2A project agent: /.well-known/agent-card.json + /a2a,
# in-process (same uvicorn worker, same event loop as the engine above).
app.include_router(a2a_router)

# The project's own frontend (frontend/dist, a Vite build with base=/demo/),
# served same-origin so the card's live-demo extension (a2a_agent.py) can
# point at this engine's own address instead of a separate origin. Guarded:
# absent in environments that don't ship the frontend build (e.g. a stripped
# test image), the engine still boots fine without it.
_frontend_dist = Path(__file__).parent.parent / "frontend" / "dist"
if _frontend_dist.is_dir():
    app.mount("/demo", StaticFiles(directory=_frontend_dist, html=True), name="demo")
    logger.info("Serving frontend demo from %s at /demo", _frontend_dist)
else:
    logger.warning("frontend/dist not found at %s -- /demo will 404", _frontend_dist)

class CreateStoryRequest(BaseModel):
    user_id: str = "local_tester" # Match frontend string

@app.post("/stories")
async def create_story(req: CreateStoryRequest):
    """
    Creates a new narrative session in the ADK Database.
    Returns the session_id to connect via WebSocket.
    """
    from src.services.session_manager import create_fable_session
    session_id = await create_fable_session(user_id=req.user_id)
    logger.info(f"New story session initialized in ADK: {session_id} for user {req.user_id}")
    return {"session_id": session_id}


@app.get("/stories/{user_id}")
async def list_stories(user_id: str):
    """
    Lists all sessions for a user that have at least a story premise set.
    Used by the home screen to show resumable stories.
    """
    from src.services.session_manager import session_service
    try:
        response = await session_service.list_sessions(
            app_name="fable_2_0",
            user_id=user_id,
        )
        sessions = getattr(response, "sessions", response) or []
    except Exception as e:
        logger.error(f"Failed to list sessions for user {user_id}: {e}")
        return {"stories": []}

    stories = []
    for s in sessions:
        state = getattr(s, "state", None) or {}
        raw_premise = state.get("story_premise") or ""
        story_premise = raw_premise if isinstance(raw_premise, str) else str(raw_premise)

        power_debt = state.get("power_debt") or {}
        power_debt_level = int(power_debt.get("strain_level", 0)) if isinstance(power_debt, dict) else 0
        last_update = getattr(s, "last_update_time", None)

        def _str(val: object, default: str = "Unknown") -> str:
            return val if isinstance(val, str) else (str(val) if val else default)

        stories.append({
            "session_id": s.id,
            "chapter": int(state.get("chapter_count") or 1),
            "location": _str(state.get("current_location_node"), "Unknown"),
            "mood": _str(state.get("current_mood"), "Neutral"),
            "story_premise": story_premise[:150],
            "setup_complete": bool(state.get("last_story_text", "")),
            "power_debt_level": power_debt_level,
            "last_update": last_update.isoformat() if hasattr(last_update, "isoformat") else (str(last_update) if last_update else None),
        })

    stories.sort(key=lambda x: x.get("last_update") or "", reverse=True)
    return {"stories": stories}


@app.delete("/stories/{user_id}/{session_id}")
async def delete_story(user_id: str, session_id: str):
    """Permanently removes a session from the ADK database AND cascades the
    per-session protagonist LoreNode + its edges + embeddings.

    The lore tables (LoreNode/LoreEdge/LoreEmbedding) have no session
    column by design -- canon-research embeddings are universally reusable
    across stories. The ONE exception is the per-session "PROTAGONIST::..."
    sentinel node and any edges anchored on it (written by the archivist's
    update_relationship tool); those are story-specific and must be nuked
    when the story is deleted.
    """
    from src.services.session_manager import session_service
    try:
        # 1. Capture the per-session protagonist sentinel BEFORE deleting the session.
        protagonist_name = None
        try:
            existing = await session_service.get_session(
                app_name="fable_2_0",
                user_id=user_id,
                session_id=session_id,
            )
            if existing:
                state = getattr(existing, "state", {}) or {}
                pn = state.get("protagonist_node_name")
                if isinstance(pn, str) and pn.startswith("PROTAGONIST::"):
                    protagonist_name = pn
        except Exception as snap_err:
            logger.warning("Pre-delete state snapshot failed for %s: %s", session_id, snap_err)

        # 2. Delete the ADK session (sessions/events/state rows).
        await session_service.delete_session(
            app_name="fable_2_0",
            user_id=user_id,
            session_id=session_id,
        )
        logger.info("Deleted session %s for user %s", session_id, user_id)

        # 3. Cascade-delete the per-session protagonist node + edges + embeddings.
        if protagonist_name:
            from sqlalchemy import select, delete
            from src.database import AsyncSessionLocal
            from src.state.lore_models import LoreNode, LoreEdge, LoreEmbedding
            try:
                async with AsyncSessionLocal() as db:
                    node_stmt = select(LoreNode).where(LoreNode.name == protagonist_name)
                    node = (await db.execute(node_stmt)).scalar_one_or_none()
                    if node is not None:
                        # Edges have no FK cascade in the schema; remove explicitly.
                        await db.execute(delete(LoreEdge).where(
                            (LoreEdge.source_id == node.id) | (LoreEdge.target_id == node.id)
                        ))
                        # Cascade=all,delete-orphan on LoreNode.embeddings should handle
                        # the embeddings, but explicitly drop in case the async DELETE
                        # path doesn't honour the relationship-level cascade.
                        await db.execute(delete(LoreEmbedding).where(LoreEmbedding.node_id == node.id))
                        await db.delete(node)
                        await db.commit()
                        logger.info("Cascade-cleaned protagonist sentinel %s", protagonist_name)
            except Exception as cascade_err:
                logger.warning(
                    "Protagonist sentinel cleanup failed for %s: %s",
                    protagonist_name, cascade_err,
                )

        return {"status": "deleted"}
    except Exception as e:
        logger.error("Failed to delete session %s: %s", session_id, e)
        raise HTTPException(status_code=500, detail="Failed to delete story")


@app.websocket("/ws/story/{session_id}")
async def story_websocket(websocket: WebSocket, session_id: str):
    """
    The primary real-time connection for the ADK 2.0 Workflow.
    """
    await manager.connect(websocket, session_id)
    try:
        # Only trigger WorldBuilder on sessions that haven't started yet.
        # Reconnecting to an in-progress story with /start injects "Begin Simulation"
        # as a choice response, which corrupts the story flow.
        from src.services.session_manager import session_service
        from src.ws.runner import emit_resume_snapshot
        existing = None
        try:
            existing = await session_service.get_session(
                app_name="fable_2_0",
                user_id="local_tester",
                session_id=session_id,
            )
        except Exception:
            existing = None

        # Session was deleted externally (e.g. via the trash icon, the
        # /stories DELETE endpoint, or a migration script). The frontend
        # still has the stale session_id in `selectedSession`. Tell it
        # explicitly so it can reset to the home screen instead of
        # crashing on a SessionNotFoundError from the runner.
        if existing is None:
            logger.info("WS connect for unknown session %s; sending session_not_found.", session_id)
            await manager.send_personal_message({
                "type": "error",
                "kind": "session_not_found",
                "message": "This story no longer exists. Returning to the home screen.",
            }, session_id)
            return  # finally clause closes the connection

        is_fresh = not (existing.state or {}).get("story_premise")

        if is_fresh:
            task = asyncio.create_task(execute_adk_turn(
                session_id=session_id,
                message_text="/start"
            ))
            manager.register_task(session_id, task)
        else:
            # Resumed session (including a NOTIFY-triggered re-emit landing
            # on this same instance, e.g. a demo tool's engine action):
            # push current state, the last chapter if one is waiting on a
            # choice, and any genuinely-pending HITL. Extracted to
            # src/ws/runner.py:emit_resume_snapshot so the cross-instance
            # NOTIFY bridge (src/ws/notify_bridge.py) can reuse the exact
            # same DB-state rebuild instead of duplicating this logic.
            await emit_resume_snapshot(session_id, user_id="local_tester", existing=existing)

        while True:
            # Wait for client messages
            data = await websocket.receive_json()
            
            # 1. Handle Undo / Rewind Action
            if data.get("action") == "undo":
                invocation_id = data.get("invocation_id")
                if invocation_id:
                    logger.info(f"Rewinding session {session_id} before invocation {invocation_id}")
                    manager.cancel_active_task(session_id)
                    try:
                        from src.app_container import fable_runner
                        await fable_runner.rewind_async(
                            user_id="local_tester",
                            session_id=session_id,
                            rewind_before_invocation_id=invocation_id
                        )
                        await manager.send_personal_message({"type": "undo_complete"}, session_id)
                    except Exception as e:
                        logger.error(f"Failed to rewind: {e}")
                        await manager.send_personal_message({"type": "error", "message": "Rewind failed."}, session_id)
                continue
                
            # 2. Handle Rewrite Action -- transactional Bible rollback (Phase E)
            #
            # ADK's runner.rewind_async already computes a state delta that
            # reverses every state change since the target invocation, so the
            # World Bible naturally rolls back to its pre-chapter shape. The
            # one thing rewind cannot recover is the deleted chapter's prose
            # itself -- after rewind, last_story_text is the PREVIOUS chapter.
            # So we capture the original prose + previous summaries + the
            # chapter number BEFORE rewinding, then pass them to the rewrite
            # turn as reference context. The storyteller writes the SAME
            # chapter number with the user's modifications applied -- not a
            # different chapter. This matches v1's rewrite semantics in
            # FableWeaver/src/ws/actions/rewrite.py.
            if data.get("action") == "rewrite":
                invocation_id = data.get("invocation_id")
                instruction = data.get("instruction")
                if invocation_id and instruction:
                    logger.info(f"Rewriting session {session_id} from invocation {invocation_id} with instruction: {instruction}")
                    manager.cancel_active_task(session_id)
                    try:
                        from src.app_container import fable_runner

                        # Capture pre-rewind context so the rewrite prompt
                        # has the original chapter text + prior summaries.
                        original_chapter = ""
                        prev_summaries: list[str] = []
                        chapter_number = 0
                        try:
                            existing_session = await fable_runner.session_service.get_session(
                                app_name="fable_2_0",
                                user_id="local_tester",
                                session_id=session_id,
                            )
                            pre_state = (existing_session.state or {}) if existing_session else {}
                            original_chapter = str(pre_state.get("last_story_text", "") or "")
                            chapter_number = int(pre_state.get("chapter_count", 0) or 0)
                            summaries = pre_state.get("chapter_summaries") or []
                            if isinstance(summaries, list):
                                prev_summaries = [str(s) for s in summaries[-3:]]
                        except Exception as snap_err:
                            logger.warning(
                                "Pre-rewind snapshot failed for %s: %s. "
                                "Rewrite will proceed without original-chapter reference.",
                                session_id, snap_err,
                            )

                        await fable_runner.rewind_async(
                            user_id="local_tester",
                            session_id=session_id,
                            rewind_before_invocation_id=invocation_id,
                        )
                        await manager.send_personal_message({"type": "rewrite_started"}, session_id)

                        task = asyncio.create_task(
                            execute_adk_turn(
                                session_id=session_id,
                                rewrite_instruction=instruction,
                                original_chapter=original_chapter,
                                prev_summaries=prev_summaries,
                                rewrite_chapter_number=chapter_number,
                            )
                        )
                        manager.register_task(session_id, task)
                    except Exception as e:
                        logger.error(f"Failed to rewrite: {e}")
                        await manager.send_personal_message({"type": "error", "message": "Rewrite failed."}, session_id)
                continue
            
            # Extract routing info for normal turns
            interrupt_id = data.get("interrupt_id")
            resume_payload = data.get("resume_payload")
            message_text = data.get("message")
            question_answers = data.get("question_answers")  # Option A: chapter-choice payload

            task = asyncio.create_task(
                execute_adk_turn(
                    session_id=session_id,
                    message_text=message_text,
                    resume_payload=resume_payload,
                    interrupt_id=interrupt_id,
                    question_answers=question_answers,
                )
            )
            manager.register_task(session_id, task)
            
    except WebSocketDisconnect:
        pass
    except Exception:
        logger.exception("Unexpected error in story_websocket for session %s", session_id)
    finally:
        manager.disconnect(session_id)
