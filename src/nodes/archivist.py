from typing import Optional
from google.adk.agents.llm_agent import LlmAgent
from google.adk.agents.llm_agent_config import LlmAgentConfig

from src.tools.archivist_tools import ARCHIVIST_TOOLS

# We use the highly efficient gemini-3.1-flash-lite-preview model as requested
ARCHIVIST_MODEL = "gemini-3.1-flash-lite-preview"

def create_archivist_node() -> LlmAgent:
    """
    Creates the Archivist Node.
    In ADK 2.0 Beta, an LlmAgent can be passed directly as a sub_node in a Workflow.
    This node strictly mutates the AgentState using tool calls.
    It does not write prose to the user.
    """
    
    agent_config = LlmAgentConfig(
        name="archivist",
        description="Analyzes narrative prose and updates the World Bible state using tools.",
        model=ARCHIVIST_MODEL,
        instruction=(
            "You are an analytical archivist. Your job is to read the latest chapter generated "
            "by the Storyteller and extract state changes (trust levels, butterfly effects, power strain). "
            "You must use your provided tools to record these changes."
        )
    )
    
    # Initialize the LLM Agent
    archivist_agent = LlmAgent.from_config(agent_config, config_abs_path="")
    # By simply attaching tools, ADK 2.0 uses native Gemini Function Calling automatically
    archivist_agent.tools = ARCHIVIST_TOOLS 
    
    return archivist_agent
