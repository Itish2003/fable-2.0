"""Summarizer agent — declarative output_schema shape.

Replaces the previous direct-genai shim that escaped the framework.
Now an idiomatic ADK 2.0 LlmAgent emits a structured
``ChapterSummaryOutput``; ``summarizer_persist_node`` downstream
appends to ``state.chapter_summaries`` and writes the
``chapter_summary::<chapter_count - 1>`` LoreNode/Embedding.

Moving the persist step into a separate FunctionNode kills bug #3 (the
chapter_summary index drift caused by ``len(existing)`` indexing in the
old direct-genai version).
"""

from __future__ import annotations

import logging
from typing import Optional

from google.adk.agents.callback_context import CallbackContext
from google.adk.agents.llm_agent import LlmAgent
from google.adk.models.llm_request import LlmRequest
from google.adk.models.llm_response import LlmResponse

from src.state.chapter_summary_output import ChapterSummaryOutput

logger = logging.getLogger("fable.summarizer")

SUMMARIZER_MODEL = "gemini-3.1-flash-lite"

_SUMMARIZER_INSTRUCTION = """You are the summarizer. Produce exactly 2 concise
sentences summarising the chapter shown to you. Focus on:
- the protagonist's main action
- the consequence (cost paid, near-miss, divergence triggered, key revelation)
- any state shift (relationship, power debt, timeline)

Do NOT add conversational text. Do NOT reference chapters not in the text.
Emit your output as a single ``ChapterSummaryOutput`` with field ``summary``.
"""


async def _inject_last_chapter_prose(
    callback_context: CallbackContext,
    llm_request: LlmRequest,
) -> Optional[LlmResponse]:
    """before_model_callback: inject the chapter prose so the summarizer
    has text. ``state.last_story_text`` is populated by
    ``storyteller_merge_node`` (with the deterministic ``# Chapter N``
    header) and committed by the auditor on AUDIT PASSED."""
    state = callback_context.state
    story_text = (state.get("last_story_text") or "").strip()
    if not story_text:
        return None
    # Cap at ~24KB; lite model has plenty of context but no need to spend it.
    if len(story_text) > 24000:
        story_text = "...(truncated; latest scenes follow)\n\n" + story_text[-24000:]
    llm_request.append_instructions(
        [
            "──── CHAPTER TO SUMMARISE ────\n"
            + story_text
            + "\n──── END CHAPTER ────"
        ]
    )
    return None


def create_summarizer_node() -> LlmAgent:
    """Summarizer agent in declarative output_schema mode. One LLM call,
    one ChapterSummaryOutput. Downstream summarizer_persist_node appends
    to chapter_summaries and persists the LoreEmbedding."""
    return LlmAgent(
        name="summarizer",
        description="Summarises the most recent chapter into 2 sentences.",
        model=SUMMARIZER_MODEL,
        instruction=_SUMMARIZER_INSTRUCTION,
        before_model_callback=_inject_last_chapter_prose,
        output_schema=ChapterSummaryOutput,
        # `temp:` prefix bypasses FableAgentState schema validation; the
        # summarizer_persist consumes this once and appends to chapter_summaries.
        output_key="temp:summary_output",
    )
