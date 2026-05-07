import logging
from typing import Any, AsyncGenerator

from google.adk.workflow import node
from google.adk.agents.context import Context
from google.adk.events.event import Event
from google.adk.events.event_actions import EventActions
from google.genai import types

logger = logging.getLogger("fable.intent_router")

@node(name="intent_router")
async def run_intent_router(ctx: Context, node_input: Any) -> AsyncGenerator[Event, None]:
    """
    Evaluates the user's input to determine if they want to advance the story
    or trigger a mid-story research swarm.
    """
    user_text = ctx.state.get("last_user_choice", "")
    
    logger.info(f"Intent Router analyzing input: '{user_text}'")
    
    user_lower = user_text.lower()
    if user_lower.startswith("research:") or "look up" in user_lower:
        logger.info("Intent: Research detected. Routing to Query Planner (Swarm).")
        # Ensure the query planner gets the text as its input.
        # We yield the user_text as Content so the query_planner agent sees it.
        yield Event(
            content=types.Content(role="user", parts=[types.Part.from_text(text=user_text)]),
            actions=EventActions(route="research")
        )
    else:
        logger.info("Intent: Story advance. Routing to Storyteller.")
        yield Event(
            content=types.Content(role="user", parts=[types.Part.from_text(text=user_text)]),
            actions=EventActions(route="story")
        )
