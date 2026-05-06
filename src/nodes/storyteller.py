from typing import Optional
from google.adk.agents.llm_agent import LlmAgent
from google.adk.agents.llm_agent_config import LlmAgentConfig

from src.plugins.global_instruction import GlobalInstructionPlugin

# We use the highly efficient gemini-3.1-flash-lite-preview model as requested
STORYTELLER_MODEL = "gemini-3.1-flash-lite-preview"

def create_storyteller_node() -> LlmAgent:
    """
    Creates the Storyteller Node.
    In ADK 2.0 Beta, an LlmAgent can be passed directly as a sub_node in a Workflow.
    This node generates the primary prose.
    Formatting and Tone are handled by external plugins and schema enforcements.
    """
    
    agent_config = LlmAgentConfig(
        name="storyteller",
        description="Generates the core narrative prose.",
        model=STORYTELLER_MODEL,
        instruction=(
            "You are a master storyteller writing a crossover narrative. "
            "Write the next chapter based on the user's choices. "
            "Focus entirely on rich, evocative prose. Do not output raw JSON or internal state tags."
        )
    )
    
    # Initialize the LLM Agent
    storyteller_agent = LlmAgent.from_config(agent_config, config_abs_path="")
    
    return storyteller_agent
