"""Phase C: living World Bible substrate models.

These Pydantic models extend FableAgentState with the v1-aligned fields
that drive published-quality fanfiction prose: canon timeline pressure,
character voice fidelity, power-system enforcement with limitations,
stakes-and-consequences ledgering, knowledge boundaries, anti-Worf
floors, and multi-identity tracking. The lore_keeper populates them on
initial setup; the archivist refines/extends them per chapter.
"""
from __future__ import annotations
from typing import Optional, List, Dict
from enum import Enum

from pydantic import BaseModel, Field, ConfigDict


# ─── Canon Timeline ──────────────────────────────────────────────────────────

class EventTier(str, Enum):
    mandatory = "mandatory"  # [!!!] must appear this chapter
    high = "high"             # [!!] foreshadow / prepare
    medium = "medium"         # [!] weave in when narratively appropriate


class EventStatus(str, Enum):
    upcoming = "upcoming"
    occurred = "occurred"
    modified = "modified"
    prevented = "prevented"


class CanonEvent(BaseModel):
    """A canon-source event that the storyteller must engage with."""
    model_config = ConfigDict(extra="allow")

    event_id: str = Field(description="Stable id, e.g. 'lung_vs_undersiders' or 'div_001'")
    name: str = Field(description="Human-readable event name")
    in_world_date: str = Field(default="", description="When in canon this happens, e.g. '2011-04-15'")
    pressure_score: int = Field(default=0, ge=0, le=100, description="0-100; higher = closer in timeline / higher narrative pressure")
    tier: EventTier = Field(default=EventTier.medium)
    playbook: str = Field(default="", description="Rich narrative beats: how the event typically unfolds")
    status: EventStatus = Field(default=EventStatus.upcoming)
    notes: str = Field(default="", description="Free-form notes, e.g. why a status changed")


class CanonTimeline(BaseModel):
    events: List[CanonEvent] = Field(default_factory=list)


# ─── Character Voice Profiles ────────────────────────────────────────────────

class CharacterVoice(BaseModel):
    """Per-character speech profile the storyteller uses for dialogue fidelity."""
    model_config = ConfigDict(extra="allow")

    speech_patterns: str = Field(default="", description="Formal / casual / technical / military / archaic / etc.")
    vocabulary_level: str = Field(default="", description="Simple / educated / specialized / archaic / modern")
    verbal_tics: List[str] = Field(default_factory=list, description="Repeated phrases, filler words, mannerisms")
    topics_to_avoid: List[str] = Field(default_factory=list, description="What they deflect / refuse to discuss")
    example_dialogue: str = Field(default="", description="A characteristic line capturing tone")


# ─── Power System Enforcement ────────────────────────────────────────────────

class Technique(BaseModel):
    """A single named technique with mechanics, cost, and bounds."""
    model_config = ConfigDict(extra="allow")

    name: str
    mechanics: str = Field(default="", description="Step-by-step mechanic of the technique")
    cost: str = Field(default="", description="Stamina / cooldown / resource cost")
    limitations: List[str] = Field(default_factory=list, description="Hard limits and conditions")


class PowerSource(BaseModel):
    """An origin power (e.g. 'Cursed Spirit Manipulation') with canonical techniques."""
    model_config = ConfigDict(extra="allow")

    name: str = Field(description="Canonical name of the power source")
    universe: str = Field(default="", description="Source universe e.g. 'Jujutsu Kaisen'")
    canon_techniques: List[Technique] = Field(default_factory=list)
    signature_moves: List[str] = Field(default_factory=list)
    combat_style: str = Field(default="", description="Conceptual fighting style, e.g. 'Conceptual Saboteur'")
    oc_current_mastery: str = Field(default="", description="Where the OC is on the mastery curve right now")
    weaknesses_and_counters: List[str] = Field(default_factory=list)


class PowerOrigins(BaseModel):
    sources: List[PowerSource] = Field(default_factory=list)


# ─── Stakes & Consequences ───────────────────────────────────────────────────

class CostPaid(BaseModel):
    cost: str
    severity: str = Field(default="medium", description="low / medium / high / critical")
    chapter: int = Field(default=0)


class NearMiss(BaseModel):
    what_almost_happened: str
    saved_by: str = Field(default="")
    chapter: int = Field(default=0)


class PowerUsageDebt(BaseModel):
    uses_this_chapter: int = Field(default=0)
    strain_level: str = Field(default="low", description="low / medium / high / critical")


class PendingConsequence(BaseModel):
    """A consequence the protagonist's actions set up that MUST resolve by due_by_chapter."""
    model_config = ConfigDict(extra="allow")

    action: str = Field(description="What the OC did that triggered this")
    predicted_consequence: str = Field(description="What should happen as a result")
    due_by_chapter: int = Field(default=0, ge=0, description="Chapter by which this must resolve. 0 = unscheduled.")
    overdue: bool = Field(default=False, description="Set by the per-turn tick when due_by_chapter has passed.")


class StakesAndConsequences(BaseModel):
    costs_paid: List[CostPaid] = Field(default_factory=list)
    near_misses: List[NearMiss] = Field(default_factory=list)
    power_usage_debt: Dict[str, PowerUsageDebt] = Field(default_factory=dict)
    pending_consequences: List[PendingConsequence] = Field(default_factory=list)


# ─── Knowledge Boundaries ────────────────────────────────────────────────────

class CharacterKnowledgeLimits(BaseModel):
    knows: List[str] = Field(default_factory=list)
    suspects: List[str] = Field(default_factory=list)
    doesnt_know: List[str] = Field(default_factory=list)


class KnowledgeBoundaries(BaseModel):
    """Epistemic constraints layered on top of forbidden_concepts."""
    meta_knowledge_forbidden: List[str] = Field(default_factory=list, description="World-meta facts no in-fic character can reference")
    character_knowledge_limits: Dict[str, CharacterKnowledgeLimits] = Field(default_factory=dict)


# ─── Canon Character Integrity (Anti-Worf) ───────────────────────────────────

class CharacterIntegrity(BaseModel):
    """A protected character's competence floor and notes."""
    model_config = ConfigDict(extra="allow")

    minimum_competence: str = Field(default="", description="Things this character can ALWAYS do at baseline")
    anti_worf_notes: str = Field(default="", description="Why they must not be cheaply diminished")


# ─── Multi-Identity Tracking ─────────────────────────────────────────────────

class Identity(BaseModel):
    """A persona (civilian / hero / vigilante / undercover / etc.) the OC inhabits."""
    model_config = ConfigDict(extra="allow")

    name: str = Field(description="Display name used for this identity")
    type: str = Field(default="other", description="civilian / hero / villain / vigilante / undercover / informant / other")
    is_public: bool = Field(default=False)
    known_by: List[str] = Field(default_factory=list, description="Characters who know this identity exists")
    suspected_by: List[str] = Field(default_factory=list, description="Characters who suspect but have not confirmed")
    linked_to: List[str] = Field(default_factory=list, description="Identity keys this one is connected to")
