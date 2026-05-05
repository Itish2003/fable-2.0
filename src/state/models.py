from __future__ import annotations
from typing import Optional, List, Dict, Any, Union
from pydantic import BaseModel, Field, model_validator, ConfigDict
from enum import Enum
from google.adk.agents.base_agent import BaseAgentState

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

class FableAgentState(BaseAgentState):
    """
    Primary ADK 2.0 Agent State for Fable.
    This model contains only the 'Hot State' - variables that change turn-by-turn.
    Deep lore and static descriptions live in the GraphRAG Memory Service.
    """
    model_config = ConfigDict(extra="allow", populate_by_name=True)

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

    # Global Aesthetic Metadata
    current_mood: str = Field(default="Neutral", description="The current atmosphere/pacing of the story.")
    chapter_count: int = Field(default=1, description="Current chapter sequence number.")
