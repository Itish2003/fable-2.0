import logging
from typing import Annotated

from pydantic import BaseModel, Field

from src.state.models import FableAgentState, CharacterState, DivergenceRecord
from src.database import AsyncSessionLocal
from src.state.lore_models import LoreNode, LoreEdge
from src.utils.sanitizer import sanitize_context

from google.adk.tools.tool_context import ToolContext

logger = logging.getLogger("fable.tools")

async def update_relationship(
    target_name: str,
    trust_delta: int,
    disposition: str,
    dynamic_tags: list[str],
    tool_context: ToolContext,
) -> str:
    """
    Updates the trust level, disposition, and status tags for a specific character in the current scene.
    
    Args:
        target_name: The exact name of the character.
        trust_delta: The change in trust (-100 to 100). Positive builds trust, negative damages it.
        disposition: A short tag describing their current mood/attitude (e.g., 'angry', 'intrigued').
        dynamic_tags: A list of current status effects (e.g., 'wounded', 'suspicious', 'exhausted').
    """
    # Load state from ctx.state (the global narrative state dict)
    state = FableAgentState(**{k: tool_context.state[k] for k in tool_context.state._value.keys() | tool_context.state._delta.keys()})
    
    # Sanitize inputs
    target_name = sanitize_context(target_name)
    disposition = sanitize_context(disposition)
    dynamic_tags = [sanitize_context(tag) for tag in dynamic_tags]
    
    if target_name not in state.active_characters:
        # If they aren't in the active state yet, initialize them
        state.active_characters[target_name] = CharacterState(
            trust_level=0, disposition="neutral", is_present=True
        )
        
    char_state = state.active_characters[target_name]
    
    # Apply delta and clamp between -100 and 100
    new_trust = char_state.trust_level + trust_delta
    char_state.trust_level = max(-100, min(100, new_trust))
    
    char_state.disposition = disposition
    char_state.dynamic_tags = dynamic_tags
    
    # Persist the mutation back to ctx.state so ADK records the state_delta
    tool_context.state["active_characters"] = {
        k: v.model_dump() for k, v in state.active_characters.items()
    }
    
    # We also need to update the LoreEdge in Postgres if this is a permanent shift
    if abs(trust_delta) >= 20:
        try:
            async with AsyncSessionLocal() as db:
                # We assume the POV character is the source of the edge
                # In a real implementation, we'd need to know *who* the trust delta is relative to.
                # For now, we update the metadata.
                logger.info(f"Significant trust shift detected for {target_name}. Notifying GraphRAG.")
        except Exception as e:
            logger.error(f"Failed to sync relationship to GraphRAG: {e}")

    return f"Successfully updated relationship for {target_name}. New trust level: {char_state.trust_level}."

async def record_divergence(
    canon_event_id: str,
    description: str,
    ripple_effects: list[str],
    tool_context: ToolContext,
) -> str:
    """
    Logs a Butterfly Effect. Call this whenever the protagonist's actions cause a deviation 
    from the established canon timeline.
    
    Args:
        canon_event_id: A brief identifier for the original canon event that was altered.
        description: A clear explanation of what changed in this timeline.
        ripple_effects: A list of anticipated future consequences caused by this change.
    """
    state = FableAgentState(**{k: tool_context.state[k] for k in tool_context.state._value.keys() | tool_context.state._delta.keys()})
    
    # Sanitize inputs
    canon_event_id = sanitize_context(canon_event_id)
    description = sanitize_context(description)
    ripple_effects = [sanitize_context(effect) for effect in ripple_effects]
    
    new_divergence = DivergenceRecord(
        event_id=canon_event_id,
        description=description,
        ripple_effects=ripple_effects
    )
    state.active_divergences.append(new_divergence)
    tool_context.state["active_divergences"] = [d.model_dump() for d in state.active_divergences]
    return f"Divergence recorded: {canon_event_id}. The timeline has been altered."

async def track_power_strain(
    power_used: str,
    strain_increase: int,
    tool_context: ToolContext,
) -> str:
    """
    Updates the protagonist's power debt. Call this when the protagonist uses a significant or costly ability.
    
    Args:
        power_used: The name of the power or technique used.
        strain_increase: The amount of strain added (1-100). Heavy magic should cost more.
    """
    state = FableAgentState(**{k: tool_context.state[k] for k in tool_context.state._value.keys() | tool_context.state._delta.keys()})
    
    power_used = sanitize_context(power_used)
    
    if strain_increase <= 0:
        return "No significant strain detected."
        
    state.power_debt.strain_level += strain_increase
    if power_used not in state.power_debt.recent_feats:
        state.power_debt.recent_feats.append(power_used)
        
    tool_context.state["power_debt"] = state.power_debt.model_dump()
        
    warning = ""
    if state.power_debt.strain_level > 80:
        warning = " WARNING: Strain level critical (>80). Exhaustion penalties imminent."
        
    return f"Power strain increased by {strain_increase}. Current debt: {state.power_debt.strain_level}.{warning}"

async def advance_timeline(
    new_date: str,
    event_description: str,
    tool_context: ToolContext,
) -> str:
    """
    Advances the world clock. Call this to explicitly jump forward in time.
    
    Args:
        new_date: The new in-world date/time (e.g., '2095-04-06 Morning').
        event_description: A brief summary of what happened during the time skip.
    """
    state = FableAgentState(**{k: tool_context.state[k] for k in tool_context.state._value.keys() | tool_context.state._delta.keys()})
    
    new_date = sanitize_context(new_date)
    event_description = sanitize_context(event_description)
    
    state.current_timeline_date = new_date
    tool_context.state["current_timeline_date"] = new_date
    return f"Timeline advanced to {new_date}."

# The ADK 2.0 list of tools to provide to the ArchivistNode
ARCHIVIST_TOOLS = [
    update_relationship,
    record_divergence,
    track_power_strain,
    advance_timeline
]
