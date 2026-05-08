"""Wire-level structured output for the Storyteller agent.

ADK 2.0 ``LlmAgent.output_schema`` parses the model's response into this
shape and writes it to ``state[output_key]``. ``storyteller_merge_node``
downstream prepends the deterministic ``# Chapter N`` header from
``state.chapter_count`` and splits the parts into
``state.last_story_text`` + ``state.last_chapter_meta``.

Keeping the schema this thin (one prose string + nested ChapterOutput) is
deliberate: every wire-level constraint is a Pydantic validator that
crashes the LlmAgent invocation when the model drifts. Structural rules
like "exactly 4 choices, all 4 tiers present" live in the auditor as
routing decisions, not schema-level errors.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from src.state.chapter_output import ChapterOutput


class StorytellerOutput(BaseModel):
    """What the storyteller emits per chapter."""

    prose: str = Field(
        description=(
            "The chapter body, 4000-8000 words. Begin with sensory grounding. "
            "Do NOT include a markdown header (e.g. '# Chapter N') -- the "
            "chapter number is prepended downstream."
        )
    )
    chapter_meta: ChapterOutput


__all__ = ["StorytellerOutput"]
