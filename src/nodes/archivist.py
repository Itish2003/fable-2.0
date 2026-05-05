from typing import Optional
from google.adk.agents.llm_agent import LlmAgent
from google.adk.agents.llm_agent_config import LlmAgentConfig
from google.adk.planners.plan_re_act_planner import PlanReActPlanner

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
    
    # We configure the PlanReActPlanner to ensure the LLM forms a plan
    # before attempting to mutate the Pydantic state, ensuring schema compliance.
    planner = PlanReActPlanner(
        # We can enforce tool usage natively in ADK
        # tool_choice="any" 
    )
    
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
    archivist_agent._tools = ARCHIVIST_TOOLS 
    archivist_agent.planner = planner
    
    return archivist_agent
