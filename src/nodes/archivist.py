import logging
from typing import Any, Optional

from google.adk.agents.callback_context import CallbackContext
from google.adk.agents.llm_agent import LlmAgent
from google.adk.models.llm_request import LlmRequest
from google.adk.models.llm_response import LlmResponse
from google.adk.tools.base_tool import BaseTool
from google.adk.tools.tool_context import ToolContext
from google.genai import types

from src.tools.archivist_tools import ARCHIVIST_TOOLS

logger = logging.getLogger("fable.archivist")

# We use the highly efficient gemini-3.1-flash-lite model as requested
ARCHIVIST_MODEL = "gemini-3.1-flash-lite"

# Per-chapter tool-call caps. The archivist's mode='AUTO' + soft prompt
# rules ("never call same tool with same args twice") fails to bound
# tool calls because the model varies args slightly to evade the
# text-equality check. Result: 596 calls in one chapter, 64 LLM
# round-trips, 640K tokens.
#
# These caps are hard limits enforced via before_tool_callback. When a
# tool exceeds its cap, the callback returns a synthetic "exhausted"
# response WITHOUT running the actual tool. The model sees the response
# and learns the tool is closed; combined with the existing instruction,
# this terminates the loop.
_ARCHIVIST_TOOL_CAPS = {
    "update_relationship":       8,   # one per active character is generous
    "update_character_voice":    6,   # voices for canon characters who spoke
    "commit_lore":               6,   # genuinely-new entities only
    "track_power_strain":        4,   # rare; only on costly ability use
    "add_pending_consequence":   5,   # consequences worth queuing
    "advance_timeline":          1,   # at most once per chapter
    "record_divergence":         3,   # significant canon-altering events
    "materialize_butterfly_effect": 2,
    "advance_event_status":      4,
    "mark_knowledge_violation":  3,
    "mark_power_scaling_violation": 3,
    "report_violation":          3,
    "report_leakage":            3,
}
_COUNTER_KEY = "temp:archivist_tool_calls"


async def _cap_archivist_tools(
    tool: BaseTool,
    args: dict[str, Any],
    tool_context: ToolContext,
) -> Optional[dict]:
    """before_tool_callback: enforce per-tool AND global tool-call caps.

    Returning a non-None dict short-circuits the actual tool call and
    uses the dict as the tool's response.

    Two enforcement layers:
      1. Per-tool cap: synthetic "capped" response. The model may still
         try OTHER tools.
      2. Global budget: synthetic response PLUS
         ``tool_context.actions.escalate = True``. ADK's LlmAgent run
         loop terminates the agent on the next event when escalate is
         set, so the archivist exits immediately without another LLM
         round-trip.
    """
    counts: dict = dict(tool_context.state.get(_COUNTER_KEY) or {})
    total = sum(int(v or 0) for v in counts.values())

    # 1. Global hard-stop: terminate the LlmAgent's tool loop.
    # base_llm_flow.run_async breaks out of the while-loop once
    # last_event.is_final_response() returns True. By default an event
    # carrying a function_response is NOT final — the model gets another
    # turn. Setting skip_summarization=True makes is_final_response()
    # short-circuit to True for this event, so the flow exits without
    # another LLM round-trip. escalate=True additionally signals any
    # parent LoopAgent to stop iterating. Both flags together mirror
    # the canonical google.adk.tools.exit_loop_tool implementation.
    if total >= _ARCHIVIST_TOTAL_CALL_BUDGET:
        tool_context.actions.escalate = True
        tool_context.actions.skip_summarization = True
        logger.warning(
            "archivist: global budget exhausted (%d >= %d); escalate + "
            "skip_summarization set to terminate LlmAgent flow.",
            total, _ARCHIVIST_TOTAL_CALL_BUDGET,
        )
        return {
            "capped": True,
            "reason": "global_budget_exhausted",
            "total_calls": total,
            "budget": _ARCHIVIST_TOTAL_CALL_BUDGET,
            "message": (
                f"Global tool-call budget exhausted ({total} calls this "
                f"chapter, cap={_ARCHIVIST_TOTAL_CALL_BUDGET}). Archivist "
                f"is terminating."
            ),
        }

    # 2. Per-tool cap.
    name = tool.name
    cap = _ARCHIVIST_TOOL_CAPS.get(name)
    if cap is None:
        return None  # uncapped tool; let it through

    used = int(counts.get(name, 0))
    if used >= cap:
        logger.warning(
            "archivist: %s capped at %d (this chapter); short-circuiting.",
            name, cap,
        )
        return {
            "capped": True,
            "tool": name,
            "calls_this_chapter": used,
            "cap": cap,
            "message": (
                f"{name} has been called {used} times this chapter (cap={cap}). "
                f"Do NOT call {name} again. Either move on to a different tool "
                f"or emit your final summary text."
            ),
        }
    counts[name] = used + 1
    tool_context.state[_COUNTER_KEY] = counts
    return None  # let the tool run normally


def reset_archivist_counters(state: Any) -> None:
    """Reset per-chapter archivist counters. Hook into auditor's
    AUDIT PASSED branch so each new chapter gets a fresh budget."""
    try:
        state[_COUNTER_KEY] = {}
    except Exception:
        pass


# Hard global budget for archivist tool calls per chapter. Even if every
# per-tool cap is respected, the sum across tools (8+6+6+5+4+3+3+...) can
# still loop because each per-tool short-circuit is a synthetic
# function_response the model treats as a normal result and uses to
# justify trying ANOTHER tool. When this total trips, the
# before_tool_callback sets ``actions.escalate = True`` which is ADK's
# framework-native signal for an LlmAgent to exit its tool loop — no
# extra LLM round-trip needed.
_ARCHIVIST_TOTAL_CALL_BUDGET = 25


async def _inject_chapter_prose(
    callback_context: CallbackContext,
    llm_request: LlmRequest,
) -> Optional[LlmResponse]:
    """Inject the chapter prose so the archivist has text to analyze.

    The auditor yields a route-only event, so node_input is otherwise
    empty; we read ``state.last_story_text`` and append it as an
    instruction. Global budget enforcement lives in
    ``_cap_archivist_tools`` (escalate path), not here.
    """
    state = callback_context.state
    story_text = (state.get("last_story_text") or "").strip()
    if not story_text:
        return None
    if len(story_text) > 24000:
        story_text = "...(truncated; latest scenes follow)\n\n" + story_text[-24000:]
    counts = state.get(_COUNTER_KEY) or {}
    total_calls = sum(int(v or 0) for v in counts.values()) if isinstance(counts, dict) else 0
    payload = (
        "──── CHAPTER TO ANALYZE ────\n"
        + story_text
        + "\n──── END CHAPTER ────\n\n"
        "Extract every state change implied by this chapter via your tools. "
        f"Hard budget: {_ARCHIVIST_TOTAL_CALL_BUDGET} tool calls TOTAL across "
        f"all tools this chapter (currently used: {total_calls}). When done, "
        "emit a one-sentence confirmation."
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
        before_tool_callback=_cap_archivist_tools,
        generate_content_config=types.GenerateContentConfig(
            tool_config=types.ToolConfig(
                function_calling_config=types.FunctionCallingConfig(mode='AUTO')
            )
        ),
    )
