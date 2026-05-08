"""Structured chapter-meta schema (typed choices + meta-questions).

Nested-only schema. Used as the ``chapter_meta`` field of
:class:`StorytellerOutput`. Wire-level validators that would crash the
LlmAgent invocation on model drift have been moved to runtime checks in
the auditor (``min_length``/``max_length`` on choices/questions, and
the four-tier coverage rule). ADK's ``output_schema`` parses this on
the LlmAgent path; the auditor enforces structural rules afterwards.

Schema is ported from FableWeaver v1's narrative.py output format.
"""

from __future__ import annotations

from typing import Literal, get_args

from pydantic import BaseModel, Field

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
    power_debt_incurred: dict[str, str] = Field(default_factory=dict)
    consequences_triggered: list[str] = Field(default_factory=list)


class ChapterQuestion(BaseModel):
    """A clarifying question shaping the next chapter's tone/style."""

    question: str
    context: str = ""
    type: Literal["choice"] = "choice"
    options: list[str]


class ChapterOutput(BaseModel):
    """Structured chapter-meta tail. Nested under StorytellerOutput.chapter_meta.

    No ``min_length``/``max_length`` constraints on the wire schema and no
    ``@model_validator`` -- both crash the LlmAgent invocation on the rare
    occasion the model drifts. The auditor enforces these rules at runtime
    via :func:`validate_tiers` and explicit length checks, routing to
    'failed' (retry) or 'recovery' instead.
    """

    summary: str = Field(description="5-10 sentence summary of the chapter.")
    choices: list[Choice] = Field(
        description="4 typed choices, one of each tier (canon/divergence/character/wildcard).",
    )
    choice_timeline_notes: TimelineNotes
    timeline: TimelineMeta
    canon_elements_used: list[str] = Field(default_factory=list)
    power_limitations_shown: list[str] = Field(default_factory=list)
    stakes_tracking: StakesTracking
    character_voices_used: list[str] = Field(default_factory=list)
    questions: list[ChapterQuestion] = Field(
        description="1-2 meta-questions shaping the next chapter's tone / pacing.",
    )


def validate_tiers(choices: list[dict] | list[Choice]) -> tuple[bool, str]:
    """Runtime check: choices must surface all 4 tiers exactly once.

    Returns ``(True, "")`` on success, ``(False, reason)`` on failure.
    Auditor uses this for routing decisions.
    """
    seen: list[str] = []
    for c in choices:
        tier = c.tier if isinstance(c, Choice) else c.get("tier")
        if tier:
            seen.append(tier)
    required = set(get_args(ChoiceTier))
    actual = set(seen)
    if actual != required:
        missing = required - actual
        extra = actual - required
        return False, f"tier coverage; missing={sorted(missing)} extra={sorted(extra)}"
    if len(seen) != 4:
        return False, f"expected exactly 4 choices, got {len(seen)}"
    return True, ""


__all__ = [
    "Choice",
    "ChoiceTier",
    "TimelineNotes",
    "TimelineMeta",
    "StakesTracking",
    "ChapterQuestion",
    "ChapterOutput",
    "validate_tiers",
]
