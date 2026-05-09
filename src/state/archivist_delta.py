"""Wire-level structured output for the Archivist agent.

Replaces the imperative tool-loop the archivist used to run. The
archivist now reads the chapter prose and emits a single ``ArchivistDelta``
describing what changed; ``archivist_merge_node`` downstream applies the
delta deterministically into canonical state fields.

**Schema design choice**: every "unchanged" axis uses an empty container
default (``Field(default_factory=...)``), not ``Optional[X] = None``.
Google GenAI renders ``Optional`` as ``nullable: true``, which is patchy
on non-Vertex Gemini backends; empty containers sidestep the wire-level
format entirely while still letting the model omit any axis that didn't
change.

Schema shape mirrors the OLD imperative tools in src/tools/archivist_tools.py
(deleted in this refactor) so the merge node can reproduce every state
mutation the tool-loop used to perform.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class CharacterUpdate(BaseModel):
    """How a single character's state shifted this chapter. Mirrors the
    update_relationship tool: trust delta clamps -100..+100, disposition
    overrides, dynamic_tags merge."""

    trust_delta: int = Field(
        default=0,
        description="Signed delta to apply to trust_level. Clamped -100..+100 by the merge.",
    )
    disposition: str = Field(
        default="",
        description="New disposition word ('wary', 'allied', etc.); empty = no change.",
    )
    dynamic_tags: list[str] = Field(
        default_factory=list,
        description="Tags merged (union) into the character's tag set this chapter.",
    )
    is_present: bool | None = Field(
        default=None,
        description="True/False to flip presence; null/omit = leave unchanged.",
    )


class VoiceUpdate(BaseModel):
    """Speech-pattern profile update. Mirrors update_character_voice tool."""

    speech_patterns: str = Field(default="", description="Empty = no change.")
    vocabulary_level: str = Field(default="", description="Empty = no change.")
    verbal_tics: list[str] = Field(default_factory=list)
    topics_to_avoid: list[str] = Field(default_factory=list)
    example_dialogue: str = Field(default="", description="A characteristic line from this chapter.")


class DivergenceUpdate(BaseModel):
    """A new divergence created in this chapter. Mirrors record_divergence tool."""

    canon_event_id: str
    description: str
    ripple_effects: list[str] = Field(default_factory=list)


class MaterializedRipple(BaseModel):
    """A previously predicted ripple from a divergence has actually come true
    this chapter. Mirrors materialize_butterfly_effect tool."""

    divergence_event_id: str = Field(description="event_id of an existing active_divergences entry.")
    materialization: str = Field(description="How the ripple manifested in this chapter.")


class CanonEventStatusUpdate(BaseModel):
    """Retire an upcoming canon timeline event. Mirrors advance_event_status tool.

    ``new_status`` is a free string (not Literal) so a model drift on this
    field doesn't crash the entire archivist invocation. archivist_merge
    validates the value at runtime against {upcoming, occurred, modified,
    prevented} and falls back to 'occurred' for unrecognised values.
    """

    event_name: str = Field(default="", description="Name (or event_id) of an entry in canon_timeline.events.")
    new_status: str = Field(
        default="occurred",
        description="upcoming / occurred / modified / prevented. Empty or unknown defaults to 'occurred' in merge.",
    )
    notes: str = Field(default="", description="One-line description of how it played out.")


class PowerStrainEntry(BaseModel):
    """Strain incurred from a chapter-defining power demonstration.

    Reserve entries for genuine chapter-defining feats only. Routine
    technique use should NOT generate a PowerStrainEntry -- a skilled
    practitioner using their power competently is not a strain event.
    The 1-10 scale matches the storyteller's expectation that strain is
    a texture (used sparingly when fatigue is narratively in focus),
    not a switch (flipped by every action).
    """

    power_used: str
    strain_increase: int = Field(
        description=(
            "1-10. Reserve high values (>=7) for chapter-defining feats "
            "that would warrant an explicit fatigue beat in a manga panel. "
            "Routine competent use = 0 = skip the entry entirely."
        ),
    )


class PendingConsequenceEntry(BaseModel):
    """A consequence to fire in a future chapter. Mirrors add_pending_consequence tool."""

    action: str
    predicted_consequence: str
    due_by_chapter: int


class LoreCommitEntry(BaseModel):
    """Deferred GraphRAG entity ingestion. Mirrors commit_lore tool.

    The merge node upserts a LoreNode + LoreEmbedding for each entry so
    later chapters' lore_lookup can surface it.
    """

    entity_name: str
    node_type: str = Field(default="character", description="character / location / faction / event.")
    universe: str = Field(default="", description="Empty = use state.universes[0] or 'unknown'.")
    attributes: dict[str, str | int] = Field(
        default_factory=dict,
        description=(
            "Free-form metadata persisted onto LoreNode.attributes. "
            "Accepts string or int values to absorb model drift on numeric "
            "keys like 'age', 'power_level', 'year' (the same drift class "
            "that crashed StakesTracking.power_debt_incurred via strict "
            "dict[str, str] typing)."
        ),
    )


class ViolationEntry(BaseModel):
    """A logged audit issue. Unifies report_violation, mark_knowledge_violation,
    and mark_power_scaling_violation tools."""

    violation_type: str = Field(description="e.g., 'epistemic_leak', 'anti_worf', 'canon_break', 'power_scaling'.")
    character: str = Field(default="")
    concept: str = Field(default="")
    quote: str = Field(default="", description="Direct quote from prose that triggered the flag.")
    severity: str = Field(default="", description="minor / moderate / major / critical (optional).")


class ArchivistDelta(BaseModel):
    """Everything that changed in this chapter.

    Empty containers / empty strings mean "no change to that axis". The
    merge node applies this deterministically into canonical state fields
    in a single atomic pass.
    """

    # Character + voice
    character_updates: dict[str, CharacterUpdate] = Field(default_factory=dict)
    voice_updates: dict[str, VoiceUpdate] = Field(default_factory=dict)

    # Timeline & divergences
    new_divergences: list[DivergenceUpdate] = Field(default_factory=list)
    materialized_ripples: list[MaterializedRipple] = Field(default_factory=list)
    canon_event_status_updates: list[CanonEventStatusUpdate] = Field(default_factory=list)
    new_timeline_date: str = Field(
        default="",
        description="Free-form in-world date/time string (e.g. '2095-04-06 Morning'). Empty = no advance.",
    )
    timeline_note: str = Field(default="", description="Brief narrative summary of any time skip.")

    # Power & consequences
    power_strain: list[PowerStrainEntry] = Field(default_factory=list)
    pending_consequences: list[PendingConsequenceEntry] = Field(default_factory=list)

    # Lore graph (deferred GraphRAG ingestion)
    lore_commits: list[LoreCommitEntry] = Field(default_factory=list)

    # Audit log
    violations: list[ViolationEntry] = Field(default_factory=list)


__all__ = [
    "ArchivistDelta",
    "CharacterUpdate",
    "VoiceUpdate",
    "DivergenceUpdate",
    "MaterializedRipple",
    "CanonEventStatusUpdate",
    "PowerStrainEntry",
    "PendingConsequenceEntry",
    "LoreCommitEntry",
    "ViolationEntry",
]
