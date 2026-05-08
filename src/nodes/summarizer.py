import logging
from typing import Any, AsyncGenerator

from google.adk.workflow import node
from google.adk.agents.context import Context
from google.adk.events import Event
from google.adk.agents.llm_agent import LlmAgent
from google.genai import types

from src.state.models import FableAgentState

logger = logging.getLogger("fable.summarizer")


def create_summarizer() -> LlmAgent:
    return LlmAgent(
        name="summarizer",
        description="Summarizes the previous chapter into 2 sentences.",
        model="gemini-3.1-flash-lite",
        instruction="""
        You are a Narrative Summarizer.
        Read the provided story chapter and summarize its key events in exactly 2 concise sentences.
        Focus on major plot movements, character decisions, or consequences.
        Do not add any conversational text.
        """,
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
