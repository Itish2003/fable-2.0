import logging
from typing import Any, AsyncGenerator

from google.adk.workflow import node
from google.adk.agents.context import Context
from google.adk.events.event import Event
from google.adk.agents.llm_agent import LlmAgent
from google.adk.agents.llm_agent_config import LlmAgentConfig

logger = logging.getLogger("fable.summarizer")

def create_summarizer() -> LlmAgent:
    config = LlmAgentConfig(
        name="summarizer",
        description="Summarizes the previous chapter into 2 sentences.",
        model="gemini-3.1-flash-lite-preview",
        instruction="""
        You are a Narrative Summarizer.
        Read the provided story chapter and summarize its key events in exactly 2 concise sentences.
        Focus on major plot movements, character decisions, or consequences.
        Do not add any conversational text.
        """
    )
    return LlmAgent.from_config(config, config_abs_path="")

@node(name="summarizer_node")
async def summarizer_node(ctx: Context, node_input: Any) -> AsyncGenerator[Event, None]:
    """
    Parses the summary from the Summarizer LLM and appends it to ctx.state["chapter_summaries"].
    """
    summary_text = ""
    try:
        if hasattr(node_input, "content") and node_input.content and node_input.content.parts:
            summary_text = node_input.content.parts[0].text.strip()
    except Exception as e:
        logger.error(f"Failed to parse Summarizer output: {e}")
        
    if summary_text:
        # Access state, getting existing summaries
        summaries = ctx.state.get("chapter_summaries", [])
        
        # In case the state proxy requires explicit re-assignment to detect changes:
        new_summaries = list(summaries)
        new_summaries.append(summary_text)
        
        # Write back to state to trigger ADK persistence
        ctx.state["chapter_summaries"] = new_summaries
        logger.info(f"Appended summary. Total summaries: {len(new_summaries)}")
        
    # Yield the summary text as content so the next node (choice_generator_agent)
    # has the context of what just happened to base choices off of.
    # Alternatively, the choice generator might just read the whole state.
    # We yield the node_input (the summary) or the full state.
    # Yielding an Event to continue graph flow.
    yield Event()
