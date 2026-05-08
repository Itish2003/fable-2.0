"""Wire-level structured output for the Summarizer agent.

The model returns a single 2-sentence summary; ``summarizer_persist_node``
appends it to ``state.chapter_summaries`` and embeds it as a
``chapter_summary::<chapter_count - 1>`` LoreNode for semantic recall.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class ChapterSummaryOutput(BaseModel):
    summary: str = Field(
        description=(
            "Exactly 2 concise sentences capturing the chapter's key beats: "
            "the protagonist's action, the consequence, and any state shift."
        )
    )


__all__ = ["ChapterSummaryOutput"]
