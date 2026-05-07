import logging
from typing import Optional, Any
from google.adk.plugins.base_plugin import BasePlugin
from google.adk.agents.callback_context import CallbackContext
from google.genai import types

from src.state.models import FableAgentState

logger = logging.getLogger("fable.plugin")

class GlobalInstructionPlugin(BasePlugin):
    """
    Dynamically modulates the tone and instructions for the StorytellerNode
    based on the current AgentState (e.g., Power Debt, Mood).
    Replaces the monolithic, hardcoded tone strings from V1.
    """
    
    def __init__(self):
        super().__init__(name="global_instruction_plugin")
    
    async def before_agent_callback(
        self,
        *,
        agent: Any, # BaseAgent
        callback_context: CallbackContext,
        **kwargs
    ) -> Optional[types.Content]:
        """
        Overrides the BasePlugin callback.
        Injects pacing and tone notes based on the protagonist's current power strain.
        """
        
        # We only care about modifying the Storyteller's instructions
        if agent.name != "storyteller":
            return None
            
        # Fetch the state from the global session context
        try:
            state = FableAgentState(**{k: callback_context.state[k] for k in callback_context.state._value.keys() | callback_context.state._delta.keys()})
        except Exception:
            return None
            
        dynamic_instructions = []
        
        # 1. Evaluate Power Debt (Hot State)
        power_strain = state.power_debt.strain_level if hasattr(state, "power_debt") else 0
        
        if power_strain > 80:
            dynamic_instructions.append(
                "CRITICAL OVERRIDE: The protagonist is severely exhausted (Power Strain Critical). "
                "Emphasize the physical toll of their actions. Limit complex magic or agile movements. "
                "Their inner monologue should reflect fatigue and desperation."
            )
        elif power_strain > 50:
            dynamic_instructions.append(
                "TONE NOTE: The protagonist is feeling the strain of recent encounters. "
                "They are breathing heavily and may hesitate before using demanding abilities."
            )
            
        # 2. Evaluate Mood
        if state.current_mood == "Tense":
            dynamic_instructions.append(
                "PACING NOTE: The atmosphere is incredibly tense. Use shorter, sharper sentences. "
                "Focus on micro-expressions, ambient silence, and the feeling of impending conflict."
            )
            
        # 3. Evaluate Power Level Enforcement
        power_level = getattr(state, "power_level", "street")
        if power_level in ["continental", "planetary"]:
            dynamic_instructions.append(
                "POWER SCALE NOTE: DEMONSTRATE FULL POWER AT SCALE. DO NOT artificially limit power to create challenge. "
                "The protagonist's abilities operate on a massive scale; destruction or impact should be proportionate."
            )
            
        if dynamic_instructions:
            compiled_notes = "\n\n".join(dynamic_instructions)
            logger.info(f"Injecting dynamic tone instructions (Strain: {power_strain})")
            
            # In ADK 2.0 Beta, returning Content from before_agent_callback 
            # effectively prepends a system-style user message to the context.
            return types.Content(
                role="user",
                parts=[types.Part.from_text(text=f"[INTERNAL NARRATIVE NOTE: {compiled_notes}]")]
            )
            
        return None
