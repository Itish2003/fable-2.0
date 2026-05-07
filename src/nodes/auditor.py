import logging
from typing import Any, AsyncGenerator
from google.adk.workflow import node
from google.adk.agents.context import Context
from google.adk.events.event import Event
from google.adk.events.event_actions import EventActions

from src.state.models import FableAgentState

logger = logging.getLogger("fable.auditor")

@node(name="auditor")
async def run_auditor(
    ctx: Context,
    node_input: Any,
) -> AsyncGenerator[Event, None]:
    """
    Evaluates Epistemic Boundaries and Anti-Worf rules.
    If the Storyteller's output violates core constraints, this node
    emits a 'failed' route and the graph routes backward.
    """
    # Fetch state from global session context
    state = FableAgentState(**{k: ctx.state[k] for k in ctx.state._value.keys() | ctx.state._delta.keys()})
    if not state:
        state = FableAgentState() # Fallback
        
    story_text = ""
    if isinstance(node_input, Event) and node_input.content:
        story_text = node_input.content.parts[0].text if node_input.content.parts else ""
    elif isinstance(node_input, dict) and "text" in node_input:
         story_text = node_input["text"]
    elif isinstance(node_input, str):
        story_text = node_input
        
    logger.info(f"Auditor analyzing text length: {len(story_text)}")
    
    # 1. Epistemic Boundary Check (Dynamic)
    story_lower = story_text.lower()
    for concept in state.forbidden_concepts:
        if concept.lower() in story_lower:
            logger.warning(f"AUDIT FAILED: Epistemic leak detected. Used forbidden concept: {concept}")
            yield Event(actions=EventActions(route="failed"))
            return

    # 2. Anti-Worf Check (Dynamic)
    defeat_keywords = ["defeated", "beaten", "lost easily", "overpowered by"]
    for char_name, rule in state.anti_worf_rules.items():
        if char_name.lower() in story_lower:
            for keyword in defeat_keywords:
                if keyword in story_lower:
                    logger.warning(f"AUDIT FAILED: Anti-Worf constraint broken for {char_name}. Rule: {rule}")
                    yield Event(actions=EventActions(route="failed"))
                    return
        
    logger.info("AUDIT PASSED: Text is canon-compliant.")
    
    # Save the raw prose so downstream nodes (Summarizer, SuspicionPlugin) can read it
    ctx.state["last_story_text"] = story_text
    
    # Explicitly yield the 'passed' route so the Workflow Graph can follow the edge
    yield Event(actions=EventActions(route="passed"))
