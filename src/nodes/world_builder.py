from typing import Any, AsyncGenerator
from google.adk.workflow import node
from google.adk.agents.context import Context
from google.adk.events.request_input import RequestInput
import json
import logging

from src.state.models import FableAgentState

logger = logging.getLogger("fable.worldbuilder")

@node(name="world_builder", rerun_on_resume=True)
async def run_world_builder(
    ctx: Context,
    node_input: Any,
) -> AsyncGenerator[Any, None]:
    """
    Interactive Node for setting up a new story.
    Re-engineers the V1 FableWeaver setup flow to use ADK 2.0 RequestInput mechanics.
    """
    state_key = "world_builder_state"
    builder_state = ctx.state.get(state_key, {"step": "lore_dump"})
    
    if builder_state["step"] == "lore_dump":
        interrupt_id = "setup_lore_dump"
        resume_payload = ctx.resume_inputs.get(interrupt_id)
        
        if not resume_payload:
            yield RequestInput(
                interrupt_id=interrupt_id,
                message="Paste detailed character framework, story premise, power system details, or any structured data here.",
            )
            return
        else:
            logger.info("Received lore dump payload from frontend.")
            # ADK wraps the payload in a dictionary: {'payload': '...'}
            lore_string = resume_payload.get("payload", "") if isinstance(resume_payload, dict) else resume_payload
            ctx.state["story_premise"] = lore_string
            builder_state["step"] = "configuration"
            ctx.state[state_key] = builder_state
            
    if builder_state["step"] == "configuration":
        interrupt_id = "setup_configuration"
        resume_payload = ctx.resume_inputs.get(interrupt_id)
        
        if not resume_payload:
            # We request a structured JSON response from the frontend
            yield RequestInput(
                interrupt_id=interrupt_id,
                message="Please configure the simulation parameters (Power Level, Tone, Isolation Rules).",
            )
            return
        else:
            logger.info(f"Received configuration payload: {resume_payload}")
            try:
                # The frontend will send a JSON string for the configuration step
                config_string = resume_payload.get("payload", "") if isinstance(resume_payload, dict) else resume_payload
                config = json.loads(config_string)
            except Exception:
                config = {"power_level": "city", "story_tone": "balanced", "isolate_powerset": True}
                
            ctx.state["config"] = config
            builder_state["step"] = "complete"
            ctx.state[state_key] = builder_state
            
    if builder_state["step"] == "complete":
        logger.info("World Building Complete. Initializing State...")
        
        # Inject the state directly into the global session state dictionary.
        # This persists properly to Postgres and triggers state_delta events.
        ctx.state["story_premise"] = ctx.state.get("story_premise", "")
        config = ctx.state.get("config", {})
        ctx.state["power_level"] = config.get("power_level", "city")
        ctx.state["story_tone"] = config.get("story_tone", "balanced")
        ctx.state["isolate_powerset"] = config.get("isolate_powerset", True)
        
        ctx.state["current_timeline_date"] = "Prologue"
        ctx.state["current_mood"] = "Neutral"
        ctx.state["chapter_count"] = 1
        
        # Initialize required nested dictionaries for Pydantic validation
        ctx.state["power_debt"] = {"strain_level": 0, "recent_feats": []}
        ctx.state["active_characters"] = {}
        ctx.state["active_divergences"] = []
        ctx.state["forbidden_concepts"] = []
        ctx.state["anti_worf_rules"] = {}
        
        # We no longer yield setup_complete here, as the graph continues to the Swarm.
