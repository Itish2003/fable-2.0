"""User-choice HITL node.

Phase A's storyteller emits a fenced ``json {...}`` tail matching
``ChapterOutput`` with 4 typed choices + 1-2 meta-questions. The auditor
parses that tail and writes the ``ChapterOutput.model_dump()`` into
``state.last_chapter_meta`` alongside the canonical ``last_story_text``.

This node consumes that meta, suspends the workflow with the choices and
questions in the HITL payload, and on resume captures the user's primary
choice (string -- consumed by the intent_router) and per-question answers
(dict -- consumed by the storyteller's before_model_callback next turn).

Replaces the old ``choice_generator`` LlmAgent: the storyteller already
emits these choices structurally, so a separate LLM call to generate
them was redundant and a known failure surface.
"""
from __future__ import annotations

import json
import logging
from typing import Any, AsyncGenerator

from google.adk.workflow import node
from google.adk.agents.context import Context
from google.adk.events.request_input import RequestInput

logger = logging.getLogger("fable.user_choice_input")


_FALLBACK_CHOICES = [
    {"text": "Continue cautiously into the next scene.", "tier": "character", "tied_event": None},
    {"text": "Investigate the most recent disturbance.", "tier": "character", "tied_event": None},
    {"text": "Take an unexpected risk that breaks pattern.", "tier": "wildcard", "tied_event": None},
    {"text": "Confront the most pressing canon thread head-on.", "tier": "canon", "tied_event": None},
]


@node(name="user_choice_input", rerun_on_resume=True)
async def user_choice_input_node(ctx: Context, node_input: Any) -> AsyncGenerator[Any, None]:
    """Suspend on user_choice_selection and store the resume payload.

    On resume, ``resume_payload`` is one of:
      * dict ``{"choice": str, "question_answers": dict[str, str]}`` (new shape from frontend),
      * dict ``{"payload": <one of the above>}`` (when the runner wraps via
        ``create_request_input_response(response={"payload": ...})``),
      * plain string (legacy single-choice payload).
    """
    interrupt_id = "user_choice_selection"
    resume_payload = ctx.resume_inputs.get(interrupt_id)

    if resume_payload is not None:
        payload = resume_payload
        if isinstance(payload, dict) and "payload" in payload:
            payload = payload["payload"]

        if isinstance(payload, dict):
            ctx.state["last_user_choice"] = str(payload.get("choice", "")).strip()
            ctx.state["last_user_question_answers"] = payload.get("question_answers") or {}
        else:
            ctx.state["last_user_choice"] = str(payload).strip()
            ctx.state["last_user_question_answers"] = {}

        logger.info(
            "Recorded user choice (%d chars) and %d question answers.",
            len(ctx.state.get("last_user_choice", "")),
            len(ctx.state.get("last_user_question_answers") or {}),
        )
        return

    meta = ctx.state.get("last_chapter_meta") or {}
    choices = meta.get("choices") or []
    questions = meta.get("questions") or []

    if not choices:
        logger.warning(
            "user_choice_input: no parsed choices in last_chapter_meta; "
            "surfacing fallback options so the player isn't stranded."
        )
        choices = list(_FALLBACK_CHOICES)
        questions = []

    payload = {"choices": choices, "questions": questions}
    yield RequestInput(interrupt_id=interrupt_id, message=json.dumps(payload))
