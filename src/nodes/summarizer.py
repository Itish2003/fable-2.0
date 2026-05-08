import logging
from typing import Any, AsyncGenerator, Optional

from google.adk.agents.callback_context import CallbackContext
from google.adk.workflow import node
from google.adk.agents.context import Context
from google.adk.events import Event
from google.adk.agents.llm_agent import LlmAgent
from google.adk.models.llm_request import LlmRequest
from google.adk.models.llm_response import LlmResponse
from google.genai import types

from src.state.models import FableAgentState

logger = logging.getLogger("fable.summarizer")


async def _inject_chapter_for_summary(
    callback_context: CallbackContext,
    llm_request: LlmRequest,
) -> Optional[LlmResponse]:
    """Inject the chapter prose into the summarizer's instruction.

    Same rationale as the archivist's callback: the previous node
    (archivist) emits a tool-laden event whose final text is just a
    confirmation, not the chapter. Reading state.last_story_text and
    appending it ensures the summarizer summarises the actual prose.
    """
    state = callback_context.state
    story_text = (state.get("last_story_text") or "").strip()
    if not story_text:
        return None
    if len(story_text) > 24000:
        story_text = "...(truncated; latest scenes follow)\n\n" + story_text[-24000:]
    payload = (
        "──── CHAPTER TO SUMMARISE ────\n"
        + story_text
        + "\n──── END CHAPTER ────"
    )
    llm_request.append_instructions([payload])
    return None


def create_summarizer() -> LlmAgent:
    return LlmAgent(
        name="summarizer",
        description="Summarizes the previous chapter into 2 sentences.",
        model="gemini-3.1-flash-lite",
        instruction="""
        You are a Narrative Summarizer.
        Read the chapter prose injected into your context and summarize its
        key events in exactly 2 concise sentences. Focus on major plot
        movements, character decisions, and consequences. Do not add any
        conversational text. Do not refer to chapters that aren't in the
        provided text.
        """,
        before_model_callback=_inject_chapter_for_summary,
    )


@node(name="summarizer_node")
async def summarizer_node(ctx: Context, node_input: Any) -> AsyncGenerator[Event, None]:
    """
    Parses the summary from the Summarizer LLM and appends it to ctx.state["chapter_summaries"].
    """
    # In ADK, node_input is the output from the previous node (the Storyteller, or the Archivist).
    # Since Archivist doesn't return prose, we fetch it from the graph history.
    # Graph: Storyteller -> Auditor -> Archivist -> Summarizer.
    # Archivist returns an empty event. So node_input doesn't have the story text.
    # Pull the last story text from the public state snapshot.
    state = FableAgentState(**ctx.state.to_dict())
    story_text = state.last_story_text

    summary_text = ""
    try:
        if hasattr(node_input, "content") and node_input.content and node_input.content.parts:
            summary_text = node_input.content.parts[0].text.strip()
    except Exception as e:
        logger.error(f"Failed to parse Summarizer output: {e}")

    if summary_text:
        new_summaries = state.chapter_summaries
        new_summaries.append(summary_text)

        # Write back to state to trigger ADK persistence
        ctx.state["chapter_summaries"] = new_summaries
        logger.info(f"Appended summary. Total summaries: {len(new_summaries)}")

    # CRITICAL: The choice_generator is an LlmAgent node next in the graph.
    # If we yield an empty Event(), it receives no context. Pass the story_text
    # forward as the content so the LLM knows what to generate choices for.
    yield Event(content=types.Content(role="user", parts=[types.Part.from_text(text=story_text)]))
