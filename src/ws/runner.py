import asyncio
import logging
from typing import Optional, Any

from google.genai import types
from google.adk.workflow import NodeTimeoutError

from src.app_container import fable_runner
from src.state.chapter_output import parse_chapter_tail
from src.ws.manager import manager
# HITL helpers are not publicly re-exported from google.adk.workflow or
# google.adk.events; the underscored module is the only path to them in
# ADK 2.0 Beta. Leave the import as-is until ADK exposes a stable surface.
from google.adk.workflow.utils._workflow_hitl_utils import (  # noqa: PLC2701
    create_request_input_response,
    has_request_input_function_call,
    get_request_input_interrupt_ids,
)

logger = logging.getLogger("fable.runner_loop")


# Field-name translation: FableAgentState (server) -> frontend contract.
# The schema is frozen by the cross-agent contract; do not change without
# coordinating with Agent 5.
def _build_state_update_payload(state: dict) -> dict:
    """Project the raw session state into the agreed `state_update` shape.

    Defensive: every field has a sensible default so an empty / early-session
    state still produces a valid payload. Suppresses server-only fields
    (`forbidden_concepts`, `anti_worf_rules`).
    """
    state = state or {}

    # power_debt -> power_debt_level (int)
    power_debt = state.get("power_debt") or {}
    if isinstance(power_debt, dict):
        power_debt_level = power_debt.get("strain_level", 0) or 0
    else:
        power_debt_level = 0

    # active_characters: dict[name, CharacterState-as-dict] -> list[dict]
    raw_chars = state.get("active_characters") or {}
    active_characters = []
    if isinstance(raw_chars, dict):
        for name, char in raw_chars.items():
            if not isinstance(char, dict):
                continue
            active_characters.append({
                "name": name,
                "trust": char.get("trust_level", 0) or 0,
                "disposition": char.get("disposition", "neutral") or "neutral",
                "present": bool(char.get("is_present", False)),
            })

    # active_divergences: list[DivergenceRecord-as-dict] -> list[summary dict]
    raw_divergences = state.get("active_divergences") or []
    active_divergences = []
    if isinstance(raw_divergences, list):
        for div in raw_divergences:
            if not isinstance(div, dict):
                continue
            ripples = div.get("ripple_effects") or []
            active_divergences.append({
                "event_id": div.get("event_id", "") or "",
                "description": div.get("description", "") or "",
                "ripple_count": len(ripples) if isinstance(ripples, list) else 0,
            })

    return {
        "power_debt_level": int(power_debt_level),
        "active_characters": active_characters,
        "active_divergences": active_divergences,
        "timeline_date": state.get("current_timeline_date", "Unknown") or "Unknown",
        "location": state.get("current_location_node", "Unknown") or "Unknown",
        "mood": state.get("current_mood", "Neutral") or "Neutral",
        "chapter": int(state.get("chapter_count", 1) or 1),
    }


async def _emit_state_update(session_id: str, user_id: str) -> None:
    """Fetch the latest session state and push a `state_update` frame.

    Isolated so a session-fetch glitch never suppresses `turn_complete`.
    """
    try:
        session = await fable_runner.session_service.get_session(
            app_name=fable_runner.app_name,
            user_id=user_id,
            session_id=session_id,
        )
        payload = _build_state_update_payload(session.state if session else {})
        await manager.send_personal_message(
            {"type": "state_update", "data": payload},
            session_id,
        )
    except Exception:
        logger.exception("Failed to emit state_update for session %s", session_id)


async def _emit_chapter_meta(session_id: str, user_id: str) -> None:
    """Emit a chapter_meta WS frame from state.last_chapter_meta.

    If the field is missing (e.g. recovery turn or storyteller dropped
    its JSON tail), synthesise a minimal payload with 4 generic typed
    choices so the frontend can still render a picker. Mirrors the
    fallback that user_choice_input_node previously had.
    """
    try:
        session = await fable_runner.session_service.get_session(
            app_name=fable_runner.app_name,
            user_id=user_id,
            session_id=session_id,
        )
        state = (session.state if session else {}) or {}
        meta = state.get("last_chapter_meta")
        if not meta:
            meta = {
                "summary": "(chapter completed; structured tail missing — fallback)",
                "choices": [
                    {"text": "Confront the most pressing canon thread head-on.", "tier": "canon", "tied_event": None},
                    {"text": "Step away from canon's pull and chart your own course.", "tier": "divergence", "tied_event": None},
                    {"text": "Lean into a personal relationship or internal conflict.", "tier": "character", "tied_event": None},
                    {"text": "Take an unexpected risk that breaks pattern.", "tier": "wildcard", "tied_event": None},
                ],
                "questions": [],
            }
        await manager.send_personal_message({
            "type": "chapter_meta",
            "data": meta,
        }, session_id)
    except Exception:
        logger.exception("Failed to emit chapter_meta for session %s", session_id)


async def execute_adk_turn(
    session_id: str,
    user_id: str = "local_tester",
    message_text: Optional[str] = None,
    resume_payload: Optional[Any] = None,
    interrupt_id: Optional[str] = None,
    rewrite_instruction: Optional[str] = None,
    original_chapter: Optional[str] = None,
    prev_summaries: Optional[list[str]] = None,
    rewrite_chapter_number: Optional[int] = None,
    question_answers: Optional[dict] = None,
):
    """
    Executes a single turn of the ADK 2.0 graph.
    Filters the Event stream and pushes updates via WebSockets.
    """

    # Note: invocation_id is intentionally NOT supplied. ADK auto-generates
    # one per turn; supplying our own breaks resume semantics (rewind keys
    # off the auto-generated id).
    run_kwargs: dict = {
        "user_id": user_id,
        "session_id": session_id,
    }

    logger.info(
        "Executing turn for App: %s, Session: %s, User: %s",
        fable_runner.app_name, session_id, user_id,
    )

    # 1. Prepare Input
    if rewrite_instruction:
        # Phase E: transactional rewrite -- include the previous chapter
        # summaries + the original chapter text (truncated) as reference
        # context, plus the user's instruction. The storyteller writes the
        # SAME chapter number; do NOT diverge into a different chapter.
        prev_block = ""
        if prev_summaries:
            lines = [f"  - {s}" for s in prev_summaries if s]
            if lines:
                prev_block = (
                    "\n\n──── PREVIOUS CHAPTER SUMMARIES (for arc continuity) ────\n"
                    + "\n".join(lines)
                )
        original_block = ""
        if original_chapter:
            snippet = original_chapter[:3000]
            ellipsis = "\n...(truncated; rewrite, do not copy verbatim)" if len(original_chapter) > 3000 else ""
            original_block = (
                "\n\n──── ORIGINAL CHAPTER (for reference -- DO NOT copy) ────\n"
                + snippet + ellipsis
            )
        chap_label = (
            f" Chapter {rewrite_chapter_number}"
            if rewrite_chapter_number and rewrite_chapter_number > 0
            else " this chapter"
        )
        rewrite_message = (
            f"[SYSTEM REWRITE CONSTRAINT — REWRITE{chap_label}]\n\n"
            f"USER'S CHANGES: {rewrite_instruction}\n\n"
            f"REQUIREMENTS:\n"
            f"  - Rewrite the SAME chapter ({chap_label.strip()}) with the user's "
            f"modifications applied. Same plot beats, same characters, same setting, "
            f"same timeline position.\n"
            f"  - Apply the user's instruction throughout the rewrite.\n"
            f"  - Use the World Bible state (which has been rolled back to the "
            f"pre-chapter snapshot) as the source of truth for character / world "
            f"detail. Treat injected enforcement blocks as authoritative.\n"
            f"  - DO NOT write a different chapter. Do not skip ahead. Do not "
            f"acknowledge this instruction in the prose."
            f"{prev_block}{original_block}"
        )
        run_kwargs["new_message"] = types.Content(
            role="user",
            parts=[types.Part.from_text(text=rewrite_message)],
        )
    elif message_text and message_text != "/start":
        run_kwargs["new_message"] = types.Content(
            role="user",
            parts=[types.Part.from_text(text=message_text)],
        )
        # Option A: write the user's chapter choice + meta-question answers
        # into state via state_delta so the next workflow run sees them
        # without re-traversing setup HITLs. The intent_router reads
        # last_user_choice; the storyteller's before_model_callback uses
        # last_user_question_answers for tone shaping.
        sd: dict = {"last_user_choice": message_text}
        if question_answers:
            sd["last_user_question_answers"] = question_answers
        run_kwargs["state_delta"] = sd
    elif message_text == "/start":
        run_kwargs["new_message"] = types.Content(
            role="user",
            parts=[types.Part.from_text(text="[System: Begin Simulation]")],
        )
    elif resume_payload and interrupt_id:
        run_kwargs["new_message"] = types.Content(
            role="user",
            parts=[create_request_input_response(
                interrupt_id=interrupt_id,
                response={"payload": resume_payload},
            )],
        )

    last_invocation_id: Optional[str] = None

    try:
        generator = fable_runner.run_async(**run_kwargs)

        async for event in generator:
            # Track the invocation_id from the events themselves; this is
            # what the UI needs for later undo / rewrite (rewind keys on it).
            ev_inv_id = getattr(event, "invocation_id", None)
            if ev_inv_id:
                last_invocation_id = ev_inv_id

            # 2. Handle RequestInput (Suspension) natively via ADK utils
            if has_request_input_function_call(event):
                interrupt_ids = get_request_input_interrupt_ids(event)
                req_interrupt_id = interrupt_ids[0] if interrupt_ids else "unknown"

                # Extract the prompt message from the function call arguments
                req_message = "Please provide input."
                if event.content and event.content.parts:
                    for part in event.content.parts:
                        if part.function_call and part.function_call.id == req_interrupt_id:
                            req_message = part.function_call.args.get("message", req_message)
                            break

                logger.info("Graph Suspended by RequestInput: %s", req_interrupt_id)
                await manager.send_personal_message({
                    "type": "request_input",
                    "interrupt_id": req_interrupt_id,
                    "message": req_message,
                }, session_id)
                continue

            # 3. Handle Standard Events (Node Output) — identify the inner
            #    agent via `node_name` (Workflow wraps every event with
            #    author='fable_main_workflow', so author is useless here).
            #    Inner LlmAgents inside a Workflow run with stream=False, so
            #    we emit the full final response as a single text_delta
            #    rather than waiting for partials that never come.
            if event.content and event.content.parts:
                text = event.content.parts[0].text
                node_name = getattr(event, "node_name", None) or getattr(event, "author", "system")

                if node_name == "storyteller" and text and event.is_final_response():
                    # Strip the fenced ```json {...}``` tail so the player
                    # only sees prose. The auditor downstream re-parses the
                    # same tail and writes ChapterOutput to state.last_chapter_meta;
                    # user_choice_input_node consumes it for the HITL panel.
                    # Stripping here is purely cosmetic for the reader.
                    prose, _meta = parse_chapter_tail(text)
                    await manager.send_personal_message({
                        "type": "text_delta",
                        "author": "storyteller",
                        "text": prose,
                    }, session_id)
                # Non-storyteller nodes (archivist, summarizer, choice_generator,
                # lore_keeper) stay silent — their output is JSON or tool calls,
                # not prose for the player.
            

            # 4. Handle Tool Calls via the public Event accessor.
            #    `EventActions.tool_calls` does not exist in ADK 2.0; function
            #    calls live on `Event.content.parts[*].function_call`.
            for fc in event.get_function_calls() or []:
                await manager.send_personal_message(
                    {"type": "status", "message": f"Writing to Lore Bible: {fc.name}..."},
                    session_id,
                )

        # Generator exhausted — emit state snapshot, chapter_meta (Option A:
        # the channel that carries typed choices + meta-questions to the
        # frontend; replaces the old user_choice_selection HITL), then
        # the terminal marker.
        await _emit_state_update(session_id, user_id)
        await _emit_chapter_meta(session_id, user_id)
        await manager.send_personal_message({
            "type": "turn_complete",
            "invocation_id": last_invocation_id,
        }, session_id)

    except asyncio.CancelledError:
        # Never swallow cancellation — it's how rewinds / disconnects abort
        # the in-flight turn.
        raise
    except NodeTimeoutError as e:
        logger.exception("ADK NodeTimeout during turn: %s", e)
        await manager.send_personal_message({
            "type": "error",
            "kind": "timeout",
            "message": "A weave step timed out. Please try again.",
        }, session_id)
    except Exception:
        logger.exception("Error during ADK turn execution")
        await manager.send_personal_message({
            "type": "error",
            "message": "The narrative weave destabilized. Please try again.",
        }, session_id)
