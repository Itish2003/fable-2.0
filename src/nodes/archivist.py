"""Archivist agent — declarative output_schema shape.

Replaces the imperative 13-tool LlmAgent loop. The archivist now reads
the chapter prose injected by ``_inject_chapter_prose`` and emits a
single ``ArchivistDelta`` describing every state change in this
chapter. The downstream ``archivist_merge_node`` applies that delta
deterministically to canonical state fields.

Deleted with this rewrite:
  - the per-tool cap dict (``_ARCHIVIST_TOOL_CAPS``)
  - the global tool-call budget (``_ARCHIVIST_TOTAL_CALL_BUDGET``)
  - the ``before_tool_callback=_cap_archivist_tools`` escalate hard-stop
  - the per-tool counter machinery (``_COUNTER_KEY``)
  - 13 imperative tool definitions (kept in src/tools/archivist_tools.py
    only until the merge-node-equivalent is verified to reproduce every
    state mutation; that file will be deleted in the cleanup step)

No more tool loops. No more exit conditions. One LLM call, one
structured artifact, one deterministic merge.
"""

from __future__ import annotations

import logging
from typing import Optional

from google.adk.agents.callback_context import CallbackContext
from google.adk.agents.llm_agent import LlmAgent
from google.adk.models.llm_request import LlmRequest
from google.adk.models.llm_response import LlmResponse

from src.state.archivist_delta import ArchivistDelta

logger = logging.getLogger("fable.archivist")

ARCHIVIST_MODEL = "gemini-3.1-flash-lite"

_ARCHIVIST_INSTRUCTION = """You are the analytical ARCHIVIST of Fable.

You will be given the chapter that was just generated. Your job: read
it and emit a single ``ArchivistDelta`` describing every state change
the chapter implies.

RULES:

  - Use empty containers (``[]`` / ``{}``) for axes that didn't change.
     The merge layer treats empty == "no change".
  - Do NOT include speculation. Only what the prose actually shows.
  - Do NOT inflate axes to look thorough. Six honest fields beat
     fourteen padded ones.
  - One axis per fact. If a character's trust shifted AND their voice
     was developed, fill BOTH ``character_updates`` and ``voice_updates``
     for that name.

AXIS GUIDE:

  - ``character_updates``: For each named character with a meaningful
     interaction, set trust_delta (-100..+100; positive builds, negative
     damages), disposition (short tag like "wary", "allied"), and any
     dynamic_tags worth tracking ("wounded", "suspicious"). Set
     is_present True/False if their stage status flipped.

  - ``voice_updates``: When a NEW canon character spoke for the first
     time OR an existing voice profile is stale, populate speech_patterns,
     vocabulary_level, verbal_tics, topics_to_avoid, example_dialogue.
     Skip if the character's existing profile is still accurate.

  - ``new_divergences``: ONLY when the protagonist's actions altered the
     canon timeline. canon_event_id = brief identifier of the original
     event; description = what changed; ripple_effects = anticipated
     future consequences.

  - ``materialized_ripples``: When a previously-predicted ripple from an
     existing divergence ACTUALLY HAPPENED this chapter, link it back
     via divergence_event_id and describe how it manifested.

  - ``canon_event_status_updates``: When the chapter played out an
     upcoming canon event, retire it. event_name = the event name from
     the TIMELINE block; new_status ∈ {occurred, modified, prevented};
     notes = one-line how-it-played-out.

  - ``new_timeline_date`` + ``timeline_note``: ONLY when significant
     in-world time passed (a day, a training arc, a time skip). Free-form
     date string (e.g. "2095-04-06 Morning"). Empty = no advance.

  - ``power_strain``: ONLY when the protagonist's technique was
     CHAPTER-DEFINING -- the kind of feat that would warrant an explicit
     fatigue beat in a manga panel. Routine competent use of a power
     does NOT generate an entry; skilled practitioners do their thing
     without breaking a sweat. power_used = canonical technique name;
     strain_increase = 1-10 (NOT 1-100; reserve >=7 for genuinely
     punishing feats). Most chapters should have ZERO power_strain
     entries. The storyteller, archivist_merge, and the storyteller's
     next-chapter prompt all over-react to strain numbers; only emit
     when the prose ACTUALLY depicted exhaustion or extreme cost.

  - ``pending_consequences``: For any chapter action that should produce
     a future consequence, schedule it. action = what the OC did;
     predicted_consequence = what should happen; due_by_chapter =
     current_chapter + 2..5.

  - ``lore_commits``: For genuinely-new entities (characters, factions,
     locations, events) that aren't yet in the knowledge base, commit
     them so future chapters can find them via lore_lookup. Include
     entity_name, node_type, and any attributes worth persisting.

  - ``violations``: If the prose breached an epistemic boundary,
     anti-Worf rule, or canon constraint, log it. violation_type ∈
     {epistemic_leak, anti_worf, canon_break, power_scaling, knowledge_*};
     include character + concept + the offending quote.

When there is genuinely nothing to report on an axis, omit it (empty
container / empty string / 0). The merge node treats omissions as
no-op.
"""


async def _inject_chapter_prose(
    callback_context: CallbackContext,
    llm_request: LlmRequest,
) -> Optional[LlmResponse]:
    """before_model_callback: inject the chapter prose so the archivist has
    text to analyze. The auditor and storyteller_merge run before us so
    state.last_story_text is always populated by this point."""
    state = callback_context.state
    story_text = (state.get("last_story_text") or "").strip()
    if not story_text:
        return None
    if len(story_text) > 24000:
        story_text = "...(truncated; latest scenes follow)\n\n" + story_text[-24000:]
    payload = (
        "──── CHAPTER TO ANALYZE ────\n"
        + story_text
        + "\n──── END CHAPTER ────\n\n"
        "Emit a single ArchivistDelta describing the state changes implied "
        "by this chapter. Empty containers for axes that didn't change."
    )
    llm_request.append_instructions([payload])
    return None


def create_archivist_node() -> LlmAgent:
    """Archivist agent in declarative output_schema mode. One LLM call,
    one ArchivistDelta, no tool loop. Downstream archivist_merge_node
    applies the delta to canonical state."""
    return LlmAgent(
        name="archivist",
        description="Reads a chapter and emits a structured ArchivistDelta.",
        model=ARCHIVIST_MODEL,
        instruction=_ARCHIVIST_INSTRUCTION,
        before_model_callback=_inject_chapter_prose,
        output_schema=ArchivistDelta,
        # `temp:` prefix bypasses FableAgentState schema validation; the
        # archivist_merge consumes this once and writes to canonical fields.
        output_key="temp:archivist_delta",
    )
