"""Structured-output schema for the Storyteller's chapter tail.

The Storyteller emits prose first, then a fenced ```json {...} ``` block
matching :class:`ChapterOutput`. This module owns:

* the Pydantic models for that block
* :func:`parse_chapter_tail`, the helper the runner uses to split a
  storyteller event into ``(prose, ChapterOutput | None)``.

Schema is ported from FableWeaver v1's narrative.py output format with
adaptations to v2 state-field names. See
``/Users/itish/Downloads/Fable/src/agents/narrative.py`` Phase 4 for the
v1 reference.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Literal, get_args

from pydantic import BaseModel, Field, ValidationError, model_validator

logger = logging.getLogger("fable.state.chapter_output")

ChoiceTier = Literal["canon", "divergence", "character", "wildcard"]


class Choice(BaseModel):
    """One of the four choices presented at the end of a chapter."""

    text: str
    tier: ChoiceTier
    tied_event: str | None = Field(
        default=None,
        description="Name of the upcoming canon event this choice engages, if any.",
    )


class TimelineNotes(BaseModel):
    """Pointer metadata describing how the choices interact with the timeline."""

    upcoming_event_considered: str | None = None
    canon_path_choice: int | None = Field(
        default=None,
        description="1-based index into the choices array marking the canon-path option.",
    )
    divergence_choice: int | None = Field(
        default=None,
        description="1-based index into the choices array marking the divergence option.",
    )


class TimelineMeta(BaseModel):
    """In-world time bookkeeping for the chapter."""

    chapter_start_date: str
    chapter_end_date: str
    time_elapsed: str
    canon_events_addressed: list[str] = Field(default_factory=list)
    divergences_created: list[str] = Field(default_factory=list)


class StakesTracking(BaseModel):
    """Costs, near-misses, and power-debt accumulated this chapter."""

    costs_paid: list[str] = Field(default_factory=list)
    near_misses: list[str] = Field(default_factory=list)
    # technique name -> 'low' | 'medium' | 'high' | 'critical'
    power_debt_incurred: dict[str, str] = Field(default_factory=dict)
    consequences_triggered: list[str] = Field(default_factory=list)


class ChapterQuestion(BaseModel):
    """A clarifying question shaping the next chapter's tone/style."""

    question: str
    context: str = ""
    type: Literal["choice"] = "choice"
    options: list[str]


class ChapterOutput(BaseModel):
    """Full structured tail emitted after the prose."""

    summary: str = Field(description="5-10 sentence summary of the chapter.")
    choices: list[Choice] = Field(
        ...,
        min_length=4,
        max_length=4,
        description="Exactly 4 typed choices, one of each tier (canon/divergence/character/wildcard).",
    )
    choice_timeline_notes: TimelineNotes
    timeline: TimelineMeta
    canon_elements_used: list[str] = Field(default_factory=list)
    power_limitations_shown: list[str] = Field(default_factory=list)
    stakes_tracking: StakesTracking
    character_voices_used: list[str] = Field(default_factory=list)
    questions: list[ChapterQuestion] = Field(
        ...,
        min_length=1,
        max_length=2,
        description="1-2 meta-questions shaping the next chapter's tone / pacing.",
    )

    @model_validator(mode="after")
    def _validate_tier_coverage(self):
        """Each chapter must surface all 4 tiers exactly once.
        The prompt enforces this; this validator catches drift in production."""
        tiers = {c.tier for c in self.choices}
        required = set(get_args(ChoiceTier))
        if tiers != required:
            raise ValueError(
                f"choices must cover all 4 tiers exactly once; got {sorted(tiers)}"
            )
        return self



# ─── Tail parsing ────────────────────────────────────────────────────────────

# Match the LAST ```json ... ``` block in the text. Use a non-greedy body
# inside the fence and re.DOTALL so newlines in JSON are captured. We rely
# on `re.findall` returning every match in order so the caller can pick the
# last one (storytellers occasionally emit example JSON in prose).
_FENCED_JSON_RE = re.compile(r"```json\s*(.*?)\s*```", re.DOTALL | re.IGNORECASE)


def parse_chapter_tail(prose_with_json: str) -> tuple[str, ChapterOutput | None]:
    """Split storyteller output into ``(prose, ChapterOutput | None)``.

    Locates the LAST ``` ```json ... ``` ``` block in ``prose_with_json``,
    parses it into :class:`ChapterOutput`, and returns the prose preceding
    the block paired with the parsed model.

    On any failure (no fence, malformed JSON, schema mismatch) returns
    ``(prose_with_json, None)`` so the runner can fall back to streaming
    the raw text. Failures are logged at ``warning`` level but never raise.
    """
    if not prose_with_json:
        return prose_with_json, None

    matches = list(_FENCED_JSON_RE.finditer(prose_with_json))
    if not matches:
        return prose_with_json, None

    last = matches[-1]
    json_body = last.group(1)
    prose = prose_with_json[: last.start()].rstrip()

    try:
        raw = json.loads(json_body)
    except json.JSONDecodeError as e:
        logger.warning("parse_chapter_tail: JSON decode failed: %s", e)
        return prose_with_json, None

    try:
        chapter = ChapterOutput.model_validate(raw)
    except ValidationError as e:
        logger.warning("parse_chapter_tail: schema validation failed: %s", e)
        return prose_with_json, None

    return prose, chapter


__all__ = [
    "Choice",
    "ChoiceTier",
    "TimelineNotes",
    "TimelineMeta",
    "StakesTracking",
    "ChapterQuestion",
    "ChapterOutput",
    "parse_chapter_tail",
]
