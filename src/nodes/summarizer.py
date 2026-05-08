"""Summarizer node — direct-genai version.

Phase A's design used an LlmAgent + parser-@node pair; in practice the
parser's `node_input.content.parts[0].text.strip()` parsing was returning
empty strings even when the LlmAgent produced a real summary, leaving
state.chapter_summaries empty. Diagnostic: events showed the summarizer
agent's text content matched the chapter, but summarizer_node's
state_delta was empty (no chapter_summaries write).

Now: summarizer_node does the LLM call directly. The LlmAgent shim has
been removed entirely; the workflow wires archivist_node -> summarizer_node
straight through. One node, one LLM call, state writes always land.
"""
from __future__ import annotations

import logging
import os
from typing import Any, AsyncGenerator

from google import genai
from google.adk.workflow import node
from google.adk.agents.context import Context
from google.adk.events import Event
from google.genai import types

from src.state.models import FableAgentState

logger = logging.getLogger("fable.summarizer")


async def _persist_chapter_summary_embedding(chapter_n: int, summary_text: str) -> None:
    """Embed a chapter summary into LoreEmbedding so lore_lookup surfaces it.

    Stored under a synthetic LoreNode named ``chapter_summary::<N>`` with
    node_type='chapter_summary' so future searches can filter / prefer
    these when the model asks "what happened in chapter N?". The
    chunk_text bundles the chapter number + summary so semantic search
    can find it via either the number ("Ch3", "chapter 3") or the
    content ("Mahoraga encounter", "Tatsuya betrayal").
    """
    from sqlalchemy import select
    from src.database import AsyncSessionLocal
    from src.services.embedding_service import get_embedding
    from src.state.lore_models import LoreEmbedding, LoreNode

    payload = f"Chapter {chapter_n} summary:\n{summary_text}"
    vec = await get_embedding(payload)
    node_name = f"chapter_summary::{chapter_n}"
    async with AsyncSessionLocal() as db:
        stmt = select(LoreNode).where(LoreNode.name == node_name)
        node = (await db.execute(stmt)).scalar_one_or_none()
        if node is None:
            node = LoreNode(
                name=node_name,
                node_type="chapter_summary",
                attributes={"chapter": chapter_n},
            )
            db.add(node)
            await db.flush()
        db.add(LoreEmbedding(
            node_id=node.id,
            universe="story_internal",
            volume="chapter_summaries",
            chunk_text=payload,
            embedding=vec,
        ))
        await db.commit()


_SUMMARY_PROMPT = """Summarise the chapter below in exactly 2 concise sentences.
Focus on major plot movements, character decisions, or consequences.
Do NOT add conversational text. Do NOT reference chapters not in the text.

──── CHAPTER ────
"""


async def _direct_summarise(story_text: str) -> str:
    api_key = os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY")
    if not api_key:
        # Expected in CI / dev without keys; not warning-worthy.
        logger.info("Summarizer skipped: no GOOGLE_API_KEY/GEMINI_API_KEY.")
        return ""
    if not story_text:
        return ""
    try:
        client = genai.Client(api_key=api_key)
        # Cap at ~24KB; the lite model's context is plenty but we don't
        # need to spend the budget summarising the same prose twice.
        text = (
            story_text
            if len(story_text) <= 24000
            else "...(truncated; latest scenes follow)\n\n" + story_text[-24000:]
        )
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
        chapter_n = len(existing)  # the chapter we just summarised
        logger.info("Summary appended (Ch%d total). New: %r", chapter_n, summary_text[:80])
        # Embed the summary into LoreEmbedding so the storyteller can
        # surface it via lore_lookup at chapter 10+ when the in-prompt
        # recap window has rolled past it. Fire-and-forget; failure is
        # non-fatal (the in-prompt recap is the primary path).
        try:
            await _persist_chapter_summary_embedding(chapter_n, summary_text)
        except Exception as e:
            logger.warning("Chapter summary embedding failed (Ch%d): %s", chapter_n, e)

    # Pass the chapter text forward so user_choice_input has it in scope
    # for any downstream rendering. Empty string is fine if no chapter yet.
    yield Event(
        content=types.Content(
            role="user",
            parts=[types.Part.from_text(text=story_text)],
        )
    )
