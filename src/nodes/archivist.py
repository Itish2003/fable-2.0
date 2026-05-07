from google.adk.agents.llm_agent import LlmAgent
from google.adk.planners import PlanReActPlanner
from google.genai import types

from src.tools.archivist_tools import ARCHIVIST_TOOLS

# We use the highly efficient gemini-3.1-flash-lite-preview model as requested
ARCHIVIST_MODEL = "gemini-3.1-flash-lite-preview"


def create_archivist_node() -> LlmAgent:
    """
    Creates the Archivist Node.

    The Archivist strictly mutates the AgentState via tool calls -- it never
    writes prose to the user. To guarantee schema-valid tool output, we attach:

    1. ``PlanReActPlanner`` -- forces the model to plan, act (call tools),
       reason, and only then produce a final answer.
    2. ``GenerateContentConfig.tool_config.function_calling_config(mode='ANY')``
       -- this is the actual lever that forbids free-form replies and forces
       the model to emit a function call. ``PlanReActPlanner`` itself does NOT
       accept a ``tool_choice`` argument (see
       ``google/adk/planners/plan_re_act_planner.py``); the spec's V1 wording
       was approximate.
    """
    return LlmAgent(
        name="archivist",
        description="Analyzes narrative prose and updates the World Bible state using tools.",
        model=ARCHIVIST_MODEL,
        instruction=(
            "You are an analytical archivist. Your job is to read the latest chapter generated "
            "by the Storyteller and extract state changes (trust levels, butterfly effects, power strain). "
            "You must use your provided tools to record these changes."
        ),
        tools=ARCHIVIST_TOOLS,
        planner=PlanReActPlanner(),
        generate_content_config=types.GenerateContentConfig(
            tool_config=types.ToolConfig(
                function_calling_config=types.FunctionCallingConfig(mode='ANY')
            )
        ),
    )
