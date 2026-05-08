from __future__ import annotations
from typing import Optional, List, Dict, Any, Union
from pydantic import BaseModel, Field, model_validator, ConfigDict

# Phase C: living World Bible substrate (canon timeline pressure, character
# voice fidelity, power-system enforcement, stakes ledger, knowledge
# boundaries, anti-Worf floors, multi-identity tracking).
from src.state.bible_models import (
    CanonTimeline,
    CharacterVoice,
    PowerOrigins,
    StakesAndConsequences,
    KnowledgeBoundaries,
    CharacterIntegrity,
    Identity,
)
from enum import Enum

# ─── Enums ────────────────────────────────────────────────────────────────────

class SeverityLevel(str, Enum):
    """Severity levels for stakes and divergences"""
    low = "low"
    medium = "medium"
    high = "high"
    critical = "critical"


class TrustLevel(str, Enum):
    """Trust levels for relationships"""
    complete = "complete"
    high = "high"
    medium = "medium"
    low = "low"
    strained = "strained"
    hostile = "hostile"


# ─── Component Models ─────────────────────────────────────────────────────────

class CharacterState(BaseModel):
    """Mutable character status and disposition in the current scene"""
    model_config = ConfigDict(extra="allow")

    trust_level: int = Field(default=0, ge=-100, le=100, description="Numerical trust (-100 to 100)")
    disposition: str = Field(default="neutral", description="Short tag of current mood/attitude")
    is_present: bool = Field(default=False, description="Whether the character is in the current scene")
    dynamic_tags: List[str] = Field(default_factory=list, description="Temporary status tags (e.g., 'suspicious', 'wounded')")
    last_interaction: Optional[str] = Field(default=None, description="One-sentence summary of last encounter")


class DivergenceRecord(BaseModel):
    """Butterfly effect tracking for canon deviations"""
    event_id: str = Field(description="Unique ID or date of the canon event")
    description: str = Field(description="What changed in this timeline")
    ripple_effects: List[str] = Field(default_factory=list, description="Anticipated consequences of this change")


class PowerDebt(BaseModel):
    """Strain tracking for the protagonist's abilities"""
    strain_level: int = Field(default=0, ge=0, description="Numerical strain. >80 triggers narrative penalties.")
    recent_feats: List[str] = Field(default_factory=list, description="Powers used in the current turn")


# ─── ROOT AgentState ──────────────────────────────────────────────────────────

class FableAgentState(BaseModel):
    """
    Primary ADK 2.0 Agent State for Fable.
    This model contains only the 'Hot State' - variables that change turn-by-turn.
    Deep lore and static descriptions live in the GraphRAG Memory Service.
    """
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    # Core Setup Configuration (Populated by WorldBuilder)
    story_premise: str = Field(default="", description="The core premise and character framework provided by the user.")
    power_level: str = Field(default="city", description="The scale of the protagonist's power (e.g., street, city, continental).")
    story_tone: str = Field(default="balanced", description="The overarching tone of the narrative (e.g., dark, balanced, heroic).")
    isolate_powerset: bool = Field(default=True, description="Whether the protagonist's power system is isolated from the rest of the universe's magic.")

    # Narrative Markers
    current_timeline_date: str = Field(default="Unknown", description="The current date and time in-world.")
    current_location_node: str = Field(default="Unknown", description="The primary Graph Node ID for the current location.")
    
    # protagonist State
    power_debt: PowerDebt = Field(default_factory=PowerDebt)
    
    # Active Scene Context
    active_characters: Dict[str, CharacterState] = Field(
        default_factory=dict, 
        description="Map of character names to their current scene-specific state."
    )
    
    # Butterfly Effect Tracking
    active_divergences: List[DivergenceRecord] = Field(
        default_factory=list,
        description="List of canon events that have been altered in this timeline."
    )

    # Dynamic Integrity Constraints
    forbidden_concepts: List[str] = Field(
        default_factory=list,
        description="List of concepts/names the current POV character does not know (Epistemic Boundaries)."
    )
    anti_worf_rules: Dict[str, str] = Field(
        default_factory=dict,
        description="Map of character names to their minimum competence/protection rules."
    )

    # Global Aesthetic Metadata
    current_mood: str = Field(default="Neutral", description="The current atmosphere/pacing of the story.")
    chapter_count: int = Field(default=1, description="Current chapter sequence number.")
    
    # Phase 9/12: Long-Term Memory & User Intent
    chapter_summaries: List[str] = Field(default_factory=list, description="Rolling summaries of previous chapters.")
    last_user_choice: str = Field(default="", description="The last action the user chose.")
    last_user_question_answers: Optional[Dict[str, str]] = Field(
        default=None,
        description=(
            "Per-meta-question answers from the chapter's questions[] panel. "
            "Written by execute_adk_turn as state_delta on the next chapter's "
            "run_async; consumed by the storyteller's before_model_callback "
            "next turn to shape tone/style."
        ),
    )
    last_story_text: str = Field(default="", description="The raw prose generated in the previous turn.")
    last_chapter_meta: Optional[Dict[str, Any]] = Field(
        default=None,
        description=(
            "Structured tail of the previous storyteller chapter — a "
            "ChapterOutput.model_dump() (summary, choices, timeline, "
            "stakes_tracking, etc.). Populated by the WS runner after "
            "parse_chapter_tail succeeds; consumed by Phase B for choice "
            "rendering. None when the last chapter had no parseable JSON tail."
        ),
    )

    # ─── Phase C: living World Bible substrate ───────────────────────
    canon_timeline: CanonTimeline = Field(
        default_factory=CanonTimeline,
        description="Canon-source events with pressure scores, playbooks, and status retirement. Drives [!!!]/[!!]/[!] enforcement in the storyteller's per-turn context injection.",
    )
    character_voices: Dict[str, CharacterVoice] = Field(
        default_factory=dict,
        description="Per-character speech profile (patterns / vocabulary / tics / topics_to_avoid / example_dialogue). Lookup keyed by character name.",
    )
    power_origins: PowerOrigins = Field(
        default_factory=PowerOrigins,
        description="Power-source catalog with canon techniques + limitations + OC mastery + weaknesses, used to enforce 'powers shown bound, not naked' beats.",
    )
    stakes_and_consequences: StakesAndConsequences = Field(
        default_factory=StakesAndConsequences,
        description="Costs paid, near-misses, power-usage debt, and pending consequences with due-by-chapter scheduling. Prevents 'effortless wins'.",
    )
    knowledge_boundaries: KnowledgeBoundaries = Field(
        default_factory=KnowledgeBoundaries,
        description="Epistemic constraints. meta_knowledge_forbidden complements forbidden_concepts; character_knowledge_limits restricts per-character what each persona may reference.",
    )
    canon_character_integrity: Dict[str, CharacterIntegrity] = Field(
        default_factory=dict,
        description="Per-protected-character minimum_competence + anti_worf_notes. Layered on top of the simpler anti_worf_rules dict.",
    )
    identities: Dict[str, Identity] = Field(
        default_factory=dict,
        description="Multi-persona graph (civilian / hero / vigilante / etc.) with known_by / suspected_by / linked_to edges.",
    )

    # Setup wizard conversation log (Phase D) — list of {role, content} entries.
    setup_conversation: List[Dict[str, str]] = Field(
        default_factory=list,
        description="Multi-turn USER/AI dialogue persisted as hard creative direction; consumed by query_planner.",
    )
    # Universe slugs / titles (Phase G) — drives source-universe leakage scan.
    universes: List[str] = Field(
        default_factory=list,
        description="Story universes (e.g. 'Jujutsu Kaisen', 'The Irregular at Magic High School'). Populated by lore_keeper from research summaries.",
    )
    # Phase G+: per-session sentinel for the protagonist's LoreNode.
    # Written once by world_builder at story init as
    # 'PROTAGONIST::<uuid4hex>' so each story owns a unique node and
    # update_relationship's edges don't bleed across sessions. Read by
    # archivist_tools._protagonist_name(state).
    protagonist_node_name: Optional[str] = Field(
        default=None,
        description="Per-session 'PROTAGONIST::<uuid>' sentinel; isolates story-specific LoreEdges in the GraphRAG store.",
    )

    # Auditor violation history (written by the report_violation tool)
    violation_log: List[Dict[str, Any]] = Field(default_factory=list, description="Audit trail of canon/tone violations flagged during play.")
