"""Summarizer node — direct-genai version.

Phase A's design used an LlmAgent + parser-@node pair; in practice the
parser's `node_input.content.parts[0].text.strip()` parsing was returning
empty strings even when the LlmAgent produced a real summary, leaving
state.chapter_summaries empty. Diagnostic: events showed the summarizer
agent's text content matched the chapter, but summarizer_node's
state_delta was empty (no chapter_summaries write).

Rather than continue debugging the @node-receives-agent-output plumbing,
this version does both jobs in one place: read last_story_text, ask
gemini-3.1-flash-lite directly for a 2-sentence summary, append to
state.chapter_summaries, then yield the chapter text forward as content
so user_choice_input has something to render against.
"""
from __future__ import annotations

import logging
import os
from typing import Any, AsyncGenerator

from google.adk.workflow import node
from google.adk.agents.context import Context
from google.adk.events import Event
from google.genai import types

from src.state.models import FableAgentState

logger = logging.getLogger("fable.summarizer")

# create_summarizer is retained as a compatibility shim so workflow.py's
# `summarizer_agent = create_summarizer()` import still works -- but the
# real work happens in summarizer_node below. We keep it as an LlmAgent
# wrapper so existing edges through the build_node(summarizer_agent)
# call continue to terminate correctly; the agent's output is ignored.
from google.adk.agents.llm_agent import LlmAgent


def create_summarizer() -> LlmAgent:
    """Compatibility shim. The real summarisation now happens inside
    summarizer_node via a direct genai call. This agent simply emits a
    short ack so the workflow node-graph traversal stays unchanged."""
    return LlmAgent(
        name="summarizer",
        description="Bridge node; real summarisation happens in summarizer_node.",
        model="gemini-3.1-flash-lite",
        instruction="Reply with the single word: ok",
    )


_SUMMARY_PROMPT = """Summarise the chapter below in exactly 2 concise sentences.
Focus on major plot movements, character decisions, or consequences.
Do NOT add conversational text. Do NOT reference chapters not in the text.

──── CHAPTER ────
"""


async def _direct_summarise(story_text: str) -> str:
    api_key = os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY")
    if not api_key or not story_text:
        return ""
    try:
        from google import genai
        client = genai.Client(api_key=api_key)
        # Cap at ~24KB; the lite model's context is plenty but we don't
        # need to spend the budget summarising the same prose twice.
        text = story_text if len(story_text) <= 24000 else "...(truncated; latest scenes follow)\n\n" + story_text[-24000:]
        resp = await client.aio.models.generate_content(
            model="gemini-3.1-flash-lite",
            contents=_SUMMARY_PROMPT + text,
            config=types.GenerateContentConfig(temperature=0.2),
        )
        return (resp.text or "").strip()
    except Exception as e:
        logger.warning("Direct summary call failed: %s", e)
        return ""


@node(name="summarizer_node")
async def summarizer_node(ctx: Context, node_input: Any) -> AsyncGenerator[Event, None]:
    """
    Summarise the chapter via a direct genai call and append to
    state.chapter_summaries. Yields the chapter prose forward as Content
    so the next workflow node (user_choice_input) has something to render.
    """
    try:
        state = FableAgentState(**ctx.state.to_dict())
    except Exception:
        state = FableAgentState()

    story_text = state.last_story_text or ""
    summary_text = await _direct_summarise(story_text)

    if summary_text:
        existing = list(state.chapter_summaries or [])
        existing.append(summary_text)
        ctx.state["chapter_summaries"] = existing
        logger.info("Summary appended (%d total). New: %r", len(existing), summary_text[:80])
    else:
        logger.warning("Summarizer produced no text (no API key or empty prose). Skipping append.")

    # Pass the chapter text forward so user_choice_input has it in scope
    # for any downstream rendering. Empty string is fine if no chapter yet.
    yield Event(
        content=types.Content(
            role="user",
            parts=[types.Part.from_text(text=story_text)],
        )
    )
