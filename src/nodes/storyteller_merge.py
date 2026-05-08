"""Storyteller merge node.

Runs immediately after the storyteller LlmAgent. Reads the parsed
``state.storyteller_output`` (StorytellerOutput dict produced by ADK's
output_schema path), prepends the deterministic ``# Chapter N`` header
from ``state.chapter_count``, and writes the canonical state fields the
rest of the pipeline expects (``last_story_text``, ``last_chapter_meta``).

Why this node exists: kills bug #1 (the storyteller previously had to do
arithmetic on ``state.chapter_count + 1`` to write its own header, and
the model would drift, freezing the header at "# Chapter 2" once it had
seen its own prior output as context). Now the model emits prose only;
code prepends the header from canonical state.
"""

from __future__ import annotations

import logging
from typing import Any, AsyncGenerator

from google.adk.agents.context import Context
from google.adk.events import Event
from google.adk.workflow import node

logger = logging.getLogger("fable.storyteller_merge")


@node(name="storyteller_merge")
async def storyteller_merge(
    ctx: Context, node_input: Any
) -> AsyncGenerator[Event, None]:
    out = ctx.state.get("temp:storyteller_output") or {}
    prose = (out.get("prose") or "").strip()
    chapter_meta = out.get("chapter_meta") or {}

    # chapter_count is the chapter being authored NOW (auditor increments
    # it post-pass). World_builder seeds it to 1, so chapter 1 has
    # chapter_count == 1, chapter 2 has chapter_count == 2, etc.
    chapter_n = int(ctx.state.get("chapter_count") or 1)

    last_story_text = f"# Chapter {chapter_n}\n\n{prose}" if prose else ""
    ctx.state["last_story_text"] = last_story_text
    ctx.state["last_chapter_meta"] = chapter_meta

    logger.info(
        "storyteller_merge: composed Ch%d (%d prose chars, %d choices, %d questions)",
        chapter_n,
        len(prose),
        len((chapter_meta.get("choices") or [])),
        len((chapter_meta.get("questions") or [])),
    )
    # Yield nothing visible; FunctionNode auto-commits state_delta.
    if False:
        yield  # pragma: no cover  -- keeps function async-generator-shaped
