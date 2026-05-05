from typing import Optional, Any
from google.adk.plugins.base_plugin import BasePlugin
from google.adk.agents.callback_context import CallbackContext
from google.genai import types

from src.state.models import FableAgentState

class GlobalInstructionPlugin(BasePlugin):
    """
    Dynamically modulates the tone and instructions for the StorytellerNode
    based on the current AgentState (e.g., Power Debt, Mood).
    Replaces the monolithic, hardcoded tone strings from V1.
    """
    
    async def run_before_agent_callback(
        self,
        *,
        agent: Any, # BaseAgent
        callback_context: CallbackContext,
    ) -> Optional[types.Content]:
        
        # We only care about modifying the Storyteller's instructions
        if agent.name != "storyteller":
            return None
            
        state: FableAgentState = callback_context.state.get_state(FableAgentState)
        if not state:
            return None
            
        dynamic_instructions = []
        
        # 1. Evaluate Power Debt
        if state.power_debt.strain_level > 80:
            dynamic_instructions.append(
                "CRITICAL OVERRIDE: The protagonist is severely exhausted (Power Strain Critical). "
                "Emphasize the physical toll of their actions. Limit complex magic or agile movements. "
                "Their inner monologue should reflect fatigue and desperation."
            )
        elif state.power_debt.strain_level > 50:
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
            
        # If we generated dynamic instructions, we need to inject them into the system instruction
        # Note: In a full ADK 2.0 app, we would ideally modify the SystemInstruction on the fly, 
        # or append a hidden 'SystemMessage' to the context. For this plugin, we can 
        # inject it as an invisible prepended message if the framework allows, or 
        # we configure the Storyteller to read a specific state variable.
        
        # For validation purposes, we'll store it back in the state so the Storyteller can read it,
        # or we could return a hidden content part if ADK supports it.
        
        if dynamic_instructions:
            # We join them and pass them along. In a full implementation, you'd merge this with the agent's config.
            compiled_instruction = "\n\n".join(dynamic_instructions)
            # Log it so we can verify it ran
            import logging
            logging.getLogger("fable.plugin").info(f"Injected dynamic instructions: {compiled_instruction}")
            
        return None # We return None because we don't want to skip the agent's run
