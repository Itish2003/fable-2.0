"""Summarizer persistence node.

Reads ``state.summary_output`` (ChapterSummaryOutput dict from the
summarizer LlmAgent), appends the summary to ``state.chapter_summaries``,
and persists a LoreEmbedding + LoreNode under ``chapter_summary::<N>``
for semantic recall.

**Index source**: ``chapter_count - 1`` (the chapter we just summarised --
auditor already incremented). This kills bug #3 (the index drift caused
by the old ``len(existing)`` indexing, which lost alignment whenever a
summary was silently dropped).

Fire-and-forget on the LoreEmbedding write -- failure is non-fatal
because the in-prompt recap window is the primary continuity path.
"""

from __future__ import annotations

import logging
from typing import Any, AsyncGenerator

from sqlalchemy import select

from google.adk.agents.context import Context
from google.adk.events import Event
from google.adk.workflow import node

from src.database import AsyncSessionLocal
from src.services.embedding_service import get_embedding
from src.state.lore_models import LoreEmbedding, LoreNode

logger = logging.getLogger("fable.summarizer_persist")


async def _embed_chapter_summary(chapter_n: int, summary_text: str) -> None:
    payload = f"Chapter {chapter_n} summary:\n{summary_text}"
    vec = await get_embedding(payload)
    node_name = f"chapter_summary::{chapter_n}"
    async with AsyncSessionLocal() as db:
        stmt = select(LoreNode).where(LoreNode.name == node_name)
        n = (await db.execute(stmt)).scalar_one_or_none()
        if n is None:
            n = LoreNode(
                name=node_name,
                node_type="chapter_summary",
                attributes={"chapter": chapter_n},
            )
            db.add(n)
            await db.flush()
        db.add(
            LoreEmbedding(
                node_id=n.id,
                universe="story_internal",
                volume="chapter_summaries",
                chunk_text=payload,
                embedding=vec,
            )
        )
        await db.commit()


@node(name="summarizer_persist")
async def summarizer_persist(
    ctx: Context, node_input: Any
) -> AsyncGenerator[Event, None]:
    out = ctx.state.get("summary_output") or {}
    summary_text = (out.get("summary") or "").strip()
    if not summary_text:
        logger.info("summarizer_persist: empty summary, no-op")
        if False:
            yield
        return

    existing = list(ctx.state.get("chapter_summaries") or [])
    existing.append(summary_text)
    ctx.state["chapter_summaries"] = existing

    # Index by canonical chapter number, NOT len(existing) -- the latter
    # drifts whenever a summary is silently dropped (bug #3).
    # Auditor increments chapter_count BEFORE the archivist+summarizer run,
    # so the chapter we just summarised is chapter_count - 1.
    chapter_n = int(ctx.state.get("chapter_count") or 1) - 1
    if chapter_n >= 1:
        try:
            await _embed_chapter_summary(chapter_n, summary_text)
            logger.info("summarizer_persist: embedded Ch%d summary", chapter_n)
        except Exception as e:
            logger.warning(
                "summarizer_persist: chapter_summary::%d embedding failed: %s",
                chapter_n,
                e,
            )
    else:
        logger.warning(
            "summarizer_persist: skipped embed -- chapter_count=%s implies pre-Ch1 state",
            ctx.state.get("chapter_count"),
        )

    if False:
        yield  # pragma: no cover  -- async-generator shape
