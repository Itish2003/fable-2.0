"""Targeted on-demand research tool for the Storyteller.

Phase F: gives the storyteller a way to fill an explicit canon-data gap
mid-chapter WITHOUT triggering the full 10-hunter setup swarm. One
direct Gemini call with the google-search grounding tool, synthesised
into a 1-2 paragraph summary, then persisted as a LoreEmbedding row so
future turns can retrieve it via lore_lookup. Rate-limited to 2 calls
per chapter via ``ctx.state['temp:research_calls_this_chapter']`` so
the storyteller can't spend the whole turn researching.
"""
from __future__ import annotations

import json
import logging
import os
from typing import Any, Optional

from google.adk.tools.tool_context import ToolContext
from sqlalchemy import select

from src.database import AsyncSessionLocal
from src.services.embedding_service import get_embedding
from src.state.lore_models import LoreEmbedding, LoreNode
from src.utils.sanitizer import sanitize_context

logger = logging.getLogger("fable.research_tools")

_RESEARCH_MODEL = "gemini-3.1-flash-lite-preview"
_MAX_RESEARCH_CALLS_PER_CHAPTER = 2
_COUNTER_KEY = "temp:research_calls_this_chapter"

_RESEARCH_PROMPT = """You are a Lore Researcher. Use google_search to look up the
following topic and synthesize a tight 1-2 paragraph summary covering:
  - The canonical mechanics / identity / role
  - Hard limitations or boundaries that affect storytelling
  - Key relationships or context relevant to a crossover narrative

Cite source titles inline where useful. NO markdown headers. NO meta-commentary.
Just the summary text, ready to be embedded into a lore database.

TOPIC: """


async def _direct_research(topic: str) -> Optional[str]:
    """Single direct genai call with google_search grounding.

    Returns the synthesised summary or None on failure / no API key.
    """
    api_key = os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY")
    if not api_key:
        logger.warning("trigger_research: no GOOGLE_API_KEY/GEMINI_API_KEY; skipping.")
        return None
    try:
        from google import genai
        from google.genai import types as gtypes
        client = genai.Client(api_key=api_key)
        resp = client.models.generate_content(
            model=_RESEARCH_MODEL,
            contents=_RESEARCH_PROMPT + topic,
            config=gtypes.GenerateContentConfig(
                tools=[gtypes.Tool(google_search=gtypes.GoogleSearch())],
                temperature=0.2,
            ),
        )
        text = (resp.text or "").strip()
        return text or None
    except Exception as e:
        logger.warning("trigger_research direct call failed: %s", e)
        return None


async def _persist_research(topic: str, summary: str, universe: str) -> bool:
    """Mirror the commit_lore pattern: embed and write to LoreEmbedding."""
    chunk_payload = f"{topic}\n{summary}"
    try:
        vector = await get_embedding(chunk_payload)
    except Exception as e:
        logger.error("trigger_research embedding failed for %s: %s", topic, e)
        return False
    try:
        async with AsyncSessionLocal() as db:
            stmt = select(LoreNode).where(LoreNode.name == topic)
            result = await db.execute(stmt)
            node = result.scalar_one_or_none()
            if node is None:
                node = LoreNode(
                    name=topic,
                    node_type="topic",
                    attributes={"source": "trigger_research"},
                )
                db.add(node)
                await db.flush()

            db.add(LoreEmbedding(
                node_id=node.id,
                universe=universe,
                volume="storyteller_runtime",
                chunk_text=chunk_payload,
                embedding=vector,
            ))
            await db.commit()
        return True
    except Exception as e:
        logger.error("trigger_research DB write failed for %s: %s", topic, e)
        return False


async def trigger_research(
    topic: str,
    tool_context: ToolContext,
) -> dict:
    """
    Look up a missing canon entity (faction, character, location, technique)
    via a single targeted google search + LLM synthesis, persist the result
    so future chapters benefit, and return the summary inline.

    Use sparingly: rate-limited to 2 calls per chapter. Reserve for entities
    that are NOT already covered by the active-character lore block injected
    into your prompt and that lore_lookup did not return matches for. A typical
    use is when a specific named technique, faction officer, or location
    appears for the first time mid-chapter.

    Args:
        topic: Specific, well-targeted query, e.g. "PRT ENE leadership Director Piggot Brockton Bay".
    """
    safe_topic = sanitize_context(topic)
    if not safe_topic:
        return {"committed": False, "topic": topic, "error": "empty_topic"}

    # Rate-limit
    used = int(tool_context.state.get(_COUNTER_KEY, 0) or 0)
    if used >= _MAX_RESEARCH_CALLS_PER_CHAPTER:
        logger.info("trigger_research rate-limited (used=%d, cap=%d)", used, _MAX_RESEARCH_CALLS_PER_CHAPTER)
        return {
            "committed": False,
            "topic": safe_topic,
            "error": "rate_limit",
            "summary": "(rate-limited; proceed with what you have in context)",
        }
    tool_context.state[_COUNTER_KEY] = used + 1

    summary = await _direct_research(safe_topic)
    if not summary:
        return {
            "committed": False,
            "topic": safe_topic,
            "error": "synthesis_failed",
            "summary": "(research call failed; proceed without)",
        }

    universe_hint = ""
    universes = tool_context.state.get("universes") or []
    if isinstance(universes, list) and universes:
        universe_hint = str(universes[0])

    persisted = await _persist_research(safe_topic, summary, universe_hint or "unknown")
    return {
        "committed": persisted,
        "topic": safe_topic,
        "summary": summary,
    }


def reset_research_counter(state: Any) -> None:
    """Reset the per-chapter counter. Hook this into the auditor's
    'AUDIT PASSED' branch so each new chapter gets a fresh budget."""
    try:
        state[_COUNTER_KEY] = 0
    except Exception:
        pass
