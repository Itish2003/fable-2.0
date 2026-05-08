from typing import Optional

from google.adk.agents.callback_context import CallbackContext
from google.adk.agents.llm_agent import LlmAgent
from google.adk.models.llm_request import LlmRequest
from google.adk.models.llm_response import LlmResponse
from google.genai import types

from src.tools.archivist_tools import ARCHIVIST_TOOLS

# We use the highly efficient gemini-3.1-flash-lite model as requested
ARCHIVIST_MODEL = "gemini-3.1-flash-lite"


async def _inject_chapter_prose(
    callback_context: CallbackContext,
    llm_request: LlmRequest,
) -> Optional[LlmResponse]:
    """Inject the chapter prose into the archivist's system instruction.

    The auditor yields a route-only event (no Content) before this agent
    runs, so node_input is empty. Without this callback the archivist
    would receive only its instruction and the previous LLM trace —
    nothing to actually analyze. Reading state.last_story_text and
    appending it as an instruction block gives the archivist concrete
    text to extract state changes from.
    """
    state = callback_context.state
    story_text = (state.get("last_story_text") or "").strip()
    if not story_text:
        return None
    # Cap at ~24KB so we don't dwarf the agent's instruction; chapters at
    # the 8k-word target are ~50KB, so we trim to the last ~5k words —
    # the most-recent prose is what matters for state extraction.
    if len(story_text) > 24000:
        story_text = "...(truncated; latest scenes follow)\n\n" + story_text[-24000:]
    payload = (
        "──── CHAPTER TO ANALYZE ────\n"
        + story_text
        + "\n──── END CHAPTER ────\n\n"
        "Extract every state change implied by this chapter via your tools."
    )
    llm_request.append_instructions([payload])
    return None


def create_archivist_node() -> LlmAgent:
    """
    Creates the Archivist Node.

    The Archivist mutates AgentState via tool calls and emits a brief
    confirmation when done. We use ``mode='AUTO'`` (not ``'ANY'``) because
    ``'ANY'`` forces a function call on every turn, producing an infinite
    loop. ``PlanReActPlanner`` was previously attached but disabled in
    practice: under ``mode='AUTO'`` the model treated the planner's
    ``/*PLANNING*/`` text dump as its full response and never executed
    the planned tool calls. Without the planner the model goes straight
    to function calling.

    The chapter prose is injected per-turn by ``_inject_chapter_prose``
    (before_model_callback) reading from ``state.last_story_text`` --
    the auditor yields route-only events so node_input is otherwise empty.
    """
    return LlmAgent(
        name="archivist",
        description="Analyzes narrative prose and updates the World Bible state using tools.",
        model=ARCHIVIST_MODEL,
        instruction=(
            "You are an analytical archivist. Read the chapter injected into your "
            "context and record every state change via your tools.\n\n"
            "RULES:\n"
            "- Call update_relationship for each named character with a meaningful "
            "interaction in this chapter (ONCE per character).\n"
            "- Call record_divergence ONLY if the protagonist altered the canon timeline.\n"
            "- Call track_power_strain ONLY if the protagonist used a costly ability.\n"
            "- Call advance_timeline ONLY if significant in-world time passed.\n"
            "- Call commit_lore for genuinely new entities not yet in the knowledge base.\n"
            "- Call update_character_voice when a NEW canon character speaks.\n"
            "- Call add_pending_consequence for any action that should produce a "
            "future consequence (set due_by_chapter to current chapter + 2 to 5).\n"
            "- NEVER call the same tool with the same arguments twice.\n"
            "- DO NOT skip tool calls because the chapter is uneventful -- there is "
            "ALWAYS at least one update_relationship for each character on stage.\n"
            "- After all relevant tools have been called, respond with one sentence "
            "confirming what you archived."
        ),
        tools=ARCHIVIST_TOOLS,
        before_model_callback=_inject_chapter_prose,
        generate_content_config=types.GenerateContentConfig(
            tool_config=types.ToolConfig(
                function_calling_config=types.FunctionCallingConfig(mode='AUTO')
            )
        ),
    )
