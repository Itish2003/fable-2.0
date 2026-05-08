"""World builder: collects the user's story premise + config + (Phase D)
runs a single-turn setup wizard interrogation that captures one
laser-focused clarifying answer before research kicks off.

The wizard's question targets a fusion-mechanic / identity / timeline
ambiguity in the user's premise. Its question + the user's answer get
persisted to ``state.setup_conversation`` and treated downstream as
HARD creative direction (same authority as canon rules).
"""
from __future__ import annotations

import json
import logging
import os
from typing import Any, AsyncGenerator

from google.adk.workflow import node
from google.adk.agents.context import Context
from google.adk.events import Event
from google.adk.events.request_input import RequestInput
from google.genai import types

from src.state.models import FableAgentState  # noqa: F401  (state_schema validation)

logger = logging.getLogger("fable.worldbuilder")


# ─── Setup-wizard question generation (single direct LLM call) ──────────────
# Phase D MVP: one clarifying question per story. The question must target
# a fusion-mechanic / identity / timeline-anchor ambiguity in the user's
# premise, NOT vague flavor.

_WIZARD_MODEL = "gemini-3.1-flash-lite"

_WIZARD_PROMPT = """You are the Setup Wizard for a crossover fanfiction engine.

The user has just submitted a detailed character + power-system + universe
framework. Your job: ask ONE laser-focused clarifying question that targets
a specific ambiguity in the framework that affects how the entire story
mechanically works.

Your question MUST target one of:
  1. POWER FUSION MECHANICS — how does the OC's source power register / interact
     with the destination universe's native systems? (e.g. "Does Cursed Energy
     show up on Mahouka's psion detectors?")
  2. CHARACTER IDENTITY / AFFILIATION — does the OC have a clan, organization,
     family, or political alignment that changes their starting position?
  3. TIMELINE ANCHOR — what specific in-world date or canon event does the
     story start at?
  4. ISOLATION STRATEGY — does the OC's power interact with native magic, or
     operate on a parallel system?

Do NOT ask vague flavor questions ("what's their personality?", "what's their
goal?"). The framework already covers those.

Output ONLY a JSON object:
{
  "question": "<one sentence, specific, targeting a mechanic / identity / timeline>",
  "context": "<one sentence explaining why this ambiguity matters for the story>",
  "options": ["<option 1>", "<option 2>", "<option 3>"]
}

Provide 3-5 plausible options the user can pick (last option is usually a
free-text "Other" hint). Return strictly JSON, no markdown fences.

──────────── USER FRAMEWORK ────────────
"""


async def _generate_wizard_question(premise: str) -> dict | None:
    """Async direct genai call (uses client.aio so it doesn't block the loop)."""
    api_key = os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY")
    if not api_key:
        logger.warning("Setup wizard: no GOOGLE_API_KEY/GEMINI_API_KEY; skipping interrogation.")
        return None
    try:
        from google import genai
        client = genai.Client(api_key=api_key)
        resp = await client.aio.models.generate_content(
            model=_WIZARD_MODEL,
            contents=_WIZARD_PROMPT + (premise or "(no premise provided)"),
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                temperature=0.4,
            ),
        )
        text = (resp.text or "").strip()
        if not text:
            return None
        data = json.loads(text)
        # Schema gate
        if not isinstance(data, dict) or "question" not in data or "options" not in data:
            return None
        return {
            "question": str(data.get("question", "")).strip(),
            "context": str(data.get("context", "")).strip(),
            "options": [str(o) for o in (data.get("options") or [])][:5],
        }
    except Exception as e:
        logger.warning("Setup wizard generation failed: %s", e)
        return None


@node(name="world_builder", rerun_on_resume=True)
async def run_world_builder(
    ctx: Context,
    node_input: Any,
) -> AsyncGenerator[Any, None]:
    """
    Interactive Node for setting up a new story.

    Steps (linear, advancing on each resume):
      1. lore_dump      — user pastes premise.
      2. wizard         — LLM generates one fusion-mechanic clarifying question;
                          surface via HITL; persist answer to setup_conversation.
      3. configuration  — user picks power_level / tone / isolate_powerset.
      4. complete       — yield premise + setup_conversation as content for
                          the query_planner.
    """
    state_key = "temp:world_builder_state"
    builder_state = ctx.state.get(state_key, {"step": "lore_dump"})

    # ── 1. LORE DUMP ──────────────────────────────────────────────────────
    if builder_state["step"] == "lore_dump":
        interrupt_id = "setup_lore_dump"
        resume_payload = ctx.resume_inputs.get(interrupt_id)

        if not resume_payload:
            yield RequestInput(
                interrupt_id=interrupt_id,
                message="Paste detailed character framework, story premise, power system details, or any structured data here.",
            )
            return
        else:
            logger.info("Received lore dump payload from frontend.")
            lore_string = resume_payload.get("payload", "") if isinstance(resume_payload, dict) else resume_payload
            ctx.state["story_premise"] = lore_string
            # Initialize the conversation log
            ctx.state["setup_conversation"] = [{"role": "user", "content": lore_string}]
            builder_state["step"] = "wizard"
            ctx.state[state_key] = builder_state

    # ── 2. WIZARD INTERROGATION ───────────────────────────────────────────
    if builder_state["step"] == "wizard":
        interrupt_id = "setup_wizard_question"
        resume_payload = ctx.resume_inputs.get(interrupt_id)

        if not resume_payload:
            premise = ctx.state.get("story_premise", "")
            wizard_q = await _generate_wizard_question(premise)
            if wizard_q is None:
                # Graceful skip: no API key or LLM failure. Persist a
                # synthetic note so downstream consumers aren't surprised.
                logger.info("Setup wizard skipped (no question generated). Advancing to configuration.")
                conv = list(ctx.state.get("setup_conversation") or [])
                conv.append({"role": "wizard", "content": "(skipped — no clarifying question generated)"})
                ctx.state["setup_conversation"] = conv
                builder_state["step"] = "configuration"
                ctx.state[state_key] = builder_state
            else:
                # Stash the question so the resume branch can persist it
                # alongside the user's answer.
                ctx.state["temp:wizard_pending_question"] = wizard_q
                yield RequestInput(
                    interrupt_id=interrupt_id,
                    message=json.dumps(wizard_q),
                )
                return
        else:
            answer_raw = resume_payload.get("payload", "") if isinstance(resume_payload, dict) else resume_payload
            answer = str(answer_raw).strip()
            pending_q = ctx.state.get("temp:wizard_pending_question") or {}
            question_text = pending_q.get("question", "(unknown question)")
            conv = list(ctx.state.get("setup_conversation") or [])
            conv.append({"role": "wizard", "content": question_text})
            conv.append({"role": "user", "content": answer})
            ctx.state["setup_conversation"] = conv
            ctx.state["temp:wizard_pending_question"] = None
            logger.info(
                "Wizard interrogation captured: Q=%r A=%r",
                question_text[:80], answer[:80],
            )
            builder_state["step"] = "configuration"
            ctx.state[state_key] = builder_state

    # ── 3. CONFIGURATION ──────────────────────────────────────────────────
    if builder_state["step"] == "configuration":
        interrupt_id = "setup_configuration"
        resume_payload = ctx.resume_inputs.get(interrupt_id)

        if not resume_payload:
            yield RequestInput(
                interrupt_id=interrupt_id,
                message="Please configure the simulation parameters (Power Level, Tone, Isolation Rules).",
            )
            return
        else:
            logger.info(f"Received configuration payload: {resume_payload}")
            try:
                config_string = resume_payload.get("payload", "") if isinstance(resume_payload, dict) else resume_payload
                config = json.loads(config_string)
            except Exception:
                config = {"power_level": "city", "story_tone": "balanced", "isolate_powerset": True}

            ctx.state["temp:config"] = config
            builder_state["step"] = "complete"
            ctx.state[state_key] = builder_state

    # ── 4. COMPLETE ───────────────────────────────────────────────────────
    if builder_state["step"] == "complete":
        logger.info("World Building Complete. Initializing State...")

        ctx.state["story_premise"] = ctx.state.get("story_premise", "")
        config = ctx.state.get("temp:config", {})
        ctx.state["power_level"] = config.get("power_level", "city")
        ctx.state["story_tone"] = config.get("story_tone", "balanced")
        ctx.state["isolate_powerset"] = config.get("isolate_powerset", True)

        ctx.state["current_timeline_date"] = "Prologue"
        ctx.state["current_mood"] = "Neutral"
        ctx.state["chapter_count"] = 1

        ctx.state["power_debt"] = {"strain_level": 0, "recent_feats": []}
        ctx.state["active_characters"] = {}
        ctx.state["active_divergences"] = []
        ctx.state["forbidden_concepts"] = []
        ctx.state["anti_worf_rules"] = {}

        # Pass premise + setup_conversation as content so the query_planner
        # can target research at OC power-sources mentioned in the framework
        # and use the wizard's answer as additional creative direction.
        conv_lines = []
        for entry in (ctx.state.get("setup_conversation") or []):
            role = entry.get("role", "?")
            content = entry.get("content", "")
            conv_lines.append(f"[{role.upper()}] {content}")
        conversation_block = "\n".join(conv_lines)

        planner_input = (
            f"STORY PREMISE / OC FRAMEWORK:\n{ctx.state['story_premise']}\n\n"
            f"───────── SETUP CONVERSATION (HARD CREATIVE DIRECTION) ─────────\n"
            f"{conversation_block}\n\n"
            f"───────── RESEARCH GUIDANCE ─────────\n"
            f"If the OC's powers reference a NAMED canon character (e.g. \"Gojo's powers\", "
            f"\"Tatsuya's abilities\"), generate a research target for that character "
            f"specifically — not just the universe. Their full power dossier is required."
        )
        yield Event(
            content=types.Content(
                role="user",
                parts=[types.Part.from_text(text=planner_input)],
            )
        )
