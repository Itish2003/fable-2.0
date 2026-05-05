from typing import Optional
from google.adk.workflow._llm_agent_wrapper import LlmAgentWrapper
from google.adk.agents.llm_agent import LlmAgent
from google.adk.agents.agent_config import ModelConfig, LlmAgentConfig

from src.plugins.global_instruction import GlobalInstructionPlugin

# We use the highly efficient gemini-3.1-flash-lite-preview model as requested
STORYTELLER_MODEL = ModelConfig(model_name="gemini-3.1-flash-lite-preview")

def create_storyteller_node() -> LlmAgentWrapper:
    """
    Creates the Storyteller Node using the ADK 2.0 LlmAgentWrapper.
    This node generates the primary prose and yields it.
    Formatting and Tone are handled by external plugins and schema enforcements.
    """
    
    agent_config = LlmAgentConfig(
        name="storyteller",
        description="Generates the core narrative prose.",
        model=STORYTELLER_MODEL,
        system_instruction=(
            "You are a master storyteller writing a crossover narrative. "
            "Write the next chapter based on the user's choices. "
            "Focus entirely on rich, evocative prose. Do not output raw JSON or internal state tags."
        )
    )
    
    # Initialize the LLM Agent
    storyteller_agent = LlmAgent.from_config(agent_config, config_abs_path="")
    
    # Attach our custom tone modulation plugin
    tone_plugin = GlobalInstructionPlugin()
    # In a full App integration, plugins are registered globally, 
    # but for node isolation we can conceptually attach them or pass via context.
    
    # Wrap in a Graph Node
    storyteller_node = LlmAgentWrapper(agent=storyteller_agent)
    
    return storyteller_node
