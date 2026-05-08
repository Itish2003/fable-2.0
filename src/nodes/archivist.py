from google.adk.agents.llm_agent import LlmAgent
from google.adk.planners import PlanReActPlanner
from google.genai import types

from src.tools.archivist_tools import ARCHIVIST_TOOLS

# We use the highly efficient gemini-3.1-flash-lite model as requested
ARCHIVIST_MODEL = "gemini-3.1-flash-lite"


def create_archivist_node() -> LlmAgent:
    """
    Creates the Archivist Node.

    The Archivist mutates AgentState via tool calls and emits a brief
    confirmation when done. We use ``mode='AUTO'`` (not ``'ANY'``) because
    ``'ANY'`` forces a function call on every turn, leaving the model no way
    to terminate -- it loops the same tool call forever. ``PlanReActPlanner``
    structures the reason/act cycle; ``mode='AUTO'`` lets the model exit it.
    """
    return LlmAgent(
        name="archivist",
        description="Analyzes narrative prose and updates the World Bible state using tools.",
        model=ARCHIVIST_MODEL,
        instruction=(
            "You are an analytical archivist. Read the latest chapter and record state changes using your tools.\n\n"
            "RULES:\n"
            "- Call update_relationship for each character with a meaningful interaction (ONCE per character).\n"
            "- Call record_divergence ONLY if the protagonist altered the canon timeline.\n"
            "- Call track_power_strain ONLY if the protagonist used a costly ability.\n"
            "- Call advance_timeline ONLY if significant in-world time passed.\n"
            "- Call commit_lore for genuinely new entities not yet in the knowledge base.\n"
            "- NEVER call the same tool with the same arguments twice.\n"
            "- After all relevant tools have been called, respond with one sentence confirming what you archived."
        ),
        tools=ARCHIVIST_TOOLS,
        planner=PlanReActPlanner(),
        generate_content_config=types.GenerateContentConfig(
            tool_config=types.ToolConfig(
                function_calling_config=types.FunctionCallingConfig(mode='AUTO')
            )
        ),
    )
