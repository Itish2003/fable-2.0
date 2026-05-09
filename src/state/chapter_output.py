"""Structured chapter-meta schema (typed choices + meta-questions).

Nested-only schema. Used as the ``chapter_meta`` field of
:class:`StorytellerOutput`. Wire-level constraints that would crash
the LlmAgent invocation on model drift have been moved to runtime
checks in the auditor:
  - ``min_length`` / ``max_length`` on choices/questions
  - ``Literal["canon","divergence","character","wildcard"]`` on tier
  - ``Literal["choice"]`` on question type

Every field has a default so a partial model output validates cleanly
rather than crashing -- the auditor's runtime gates are the single
source of failure routing.

Schema is ported from FableWeaver v1's narrative.py output format.
"""

from __future__ import annotations

from typing import Literal, get_args

from pydantic import BaseModel, Field

ChoiceTier = Literal["canon", "divergence", "character", "wildcard"]


class Choice(BaseModel):
    """One of the four choices presented at the end of a chapter.

    ``tier`` is intentionally a free string (not ``ChoiceTier``
    Literal): the auditor enforces tier coverage at runtime via
    ``validate_tiers`` and routes to ``failed`` for retry on drift.
    A wire-level Literal would crash the storyteller invocation
    before the auditor can route, defeating the retry path.
    """

    text: str = ""
    tier: str = Field(
        default="",
        description="One of canon / divergence / character / wildcard.",
    )
    tied_event: str = Field(
        default="",
        description="Name of the upcoming canon event this choice engages, empty if none.",
    )


class TimelineNotes(BaseModel):
    """Pointer metadata describing how the choices interact with the timeline."""

    upcoming_event_considered: str = Field(default="")
    canon_path_choice: int = Field(
        default=0,
        description="1-based index marking the canon-path option (0 = unset).",
    )
    divergence_choice: int = Field(
        default=0,
        description="1-based index marking the divergence option (0 = unset).",
    )


class TimelineMeta(BaseModel):
    """In-world time bookkeeping for the chapter."""

    chapter_start_date: str = ""
    chapter_end_date: str = ""
    time_elapsed: str = ""
    canon_events_addressed: list[str] = Field(default_factory=list)
    divergences_created: list[str] = Field(default_factory=list)


class StakesTracking(BaseModel):
    """Costs, near-misses, and power-debt accumulated this chapter."""

    costs_paid: list[str] = Field(default_factory=list)
    near_misses: list[str] = Field(default_factory=list)
    power_debt_incurred: dict[str, str] = Field(default_factory=dict)
    consequences_triggered: list[str] = Field(default_factory=list)


class ChapterQuestion(BaseModel):
    """A clarifying question shaping the next chapter's tone/style.

    ``type`` is intentionally a free string (not ``Literal["choice"]``)
    so a model drift on this field doesn't crash the agent invocation.
    """

    question: str = ""
    context: str = ""
    type: str = "choice"
    options: list[str] = Field(default_factory=list)


class ChapterOutput(BaseModel):
    """Structured chapter-meta tail. Nested under StorytellerOutput.chapter_meta.

    Every field defaulted so partial outputs validate cleanly; the
    auditor's runtime checks (length, tier coverage, content audits)
    are the single failure-routing surface.
    """

    summary: str = Field(default="", description="5-10 sentence summary of the chapter.")
    choices: list[Choice] = Field(
        default_factory=list,
        description="4 typed choices, one of each tier (canon/divergence/character/wildcard).",
    )
    choice_timeline_notes: TimelineNotes = Field(default_factory=TimelineNotes)
    timeline: TimelineMeta = Field(default_factory=TimelineMeta)
    canon_elements_used: list[str] = Field(default_factory=list)
    power_limitations_shown: list[str] = Field(default_factory=list)
    stakes_tracking: StakesTracking = Field(default_factory=StakesTracking)
    character_voices_used: list[str] = Field(default_factory=list)
    questions: list[ChapterQuestion] = Field(
        default_factory=list,
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
