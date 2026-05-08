"""Wire-level structured output for the Lore Hunter swarm.

Replaces the previous free-form prose contract. Each parallel hunter run
researches one entity and emits a single ``LoreFinding`` describing what
it found; the keeper consumes a JSON list of these.

**Schema design constraint (CRITICAL)**: ADK 2.0's ``_ParallelWorker``
cancels the entire swarm on the first sub-run validation error
(``_parallel_worker.py:113-117``). Permissive defaults are mandatory —
every field has an empty default, ``entity_type`` is a free string (not
``Literal``), no length bounds, no strict regex. A drift in one sub-run
should degrade gracefully, not cancel nine successful runs alongside it.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class LoreTechnique(BaseModel):
    """One canonical technique under a power-system finding."""

    name: str = ""
    mechanics: str = Field(
        default="",
        description="How the technique works step-by-step. Be mechanically specific.",
    )
    cost: str = Field(
        default="",
        description="What it costs the user (stamina, time, exposure, blood, etc.).",
    )
    limitations: list[str] = Field(
        default_factory=list,
        description="Hard limits, what it CANNOT do, conditions for failure.",
    )


class LoreFinding(BaseModel):
    """One per research target produced by a lore_hunter parallel run.

    The schema is intentionally flat: all fields are optional, populated
    based on ``entity_type``. Empty defaults everywhere so the keeper's
    consumer logic can rely on ``or []`` / ``or ""`` patterns.
    """

    entity_name: str = Field(
        default="",
        description="Canonical name of the researched entity (character, ability, faction, etc.).",
    )
    entity_type: str = Field(
        default="other",
        description=(
            "One of: 'character', 'ability', 'faction', 'event', 'world', 'other'. "
            "Free string — not a Literal — so a model drift on this field doesn't "
            "cancel the whole swarm. Keeper consumers should treat unrecognised "
            "values as 'other'."
        ),
    )
    summary: str = Field(
        default="",
        description="2-4 sentence synthesis of what was learned. Required-feeling, but defaultable.",
    )

    # ─── abilities / power systems ────────────────────────────────────────────
    canon_techniques: list[LoreTechnique] = Field(default_factory=list)
    weaknesses_and_counters: list[str] = Field(default_factory=list)
    combat_style: str = ""

    # ─── characters ────────────────────────────────────────────────────────────
    speech_patterns: str = ""
    vocabulary_level: str = ""
    verbal_tics: list[str] = Field(default_factory=list)
    topics_to_avoid: list[str] = Field(default_factory=list)
    example_dialogue: str = ""
    minimum_competence: str = Field(
        default="",
        description="Anti-Worf floor: what this canon character can ALWAYS do.",
    )
    knows: list[str] = Field(default_factory=list)
    suspects: list[str] = Field(default_factory=list)
    doesnt_know: list[str] = Field(default_factory=list)

    # ─── canon events ───────────────────────────────────────────────────────────
    in_world_date: str = ""
    pressure_score: int = Field(
        default=0,
        description="0-100; narrative urgency relative to story start.",
    )
    tier: str = Field(
        default="",
        description="'mandatory' / 'high' / 'medium'. Empty = unspecified.",
    )
    playbook: str = Field(
        default="",
        description="Rich beats describing how this event canonically unfolds.",
    )

    # ─── universal ──────────────────────────────────────────────────────────────
    spoilers: list[str] = Field(
        default_factory=list,
        description="Future-knowledge / future-spoilers the OC must NOT reference.",
    )
    sources: list[str] = Field(
        default_factory=list,
        description="URLs scraped during research.",
    )
    research_query: str = Field(
        default="",
        description=(
            "The original SEARCH QUERY that produced this finding. Provenance "
            "for the keeper since framework branch metadata is lost after "
            "_ParallelWorker aggregation."
        ),
    )


__all__ = ["LoreFinding", "LoreTechnique"]
