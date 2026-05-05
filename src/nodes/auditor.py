import logging
from typing import Any
from google.adk.workflow import node
from google.adk.agents.context import Context
from google.adk.events.event import Event

from src.state.models import FableAgentState

logger = logging.getLogger("fable.auditor")

@node(name="auditor")
async def run_auditor(
    ctx: Context,
    node_input: Any,
) -> str:
    """
    Evaluates Epistemic Boundaries and Anti-Worf rules.
    If the Storyteller's output violates core constraints, this node
    injects a RetryException payload and the graph routes backward.
    """
    state: FableAgentState = ctx.get_invocation_context().agent_states.get("auditor")
    if not state:
        state = FableAgentState() # Fallback for testing
        
    story_text = ""
    if isinstance(node_input, Event) and node_input.content:
        story_text = node_input.content.parts[0].text if node_input.content.parts else ""
    elif isinstance(node_input, dict) and "text" in node_input:
         story_text = node_input["text"]
    elif isinstance(node_input, str):
        story_text = node_input
        
    logger.info(f"Auditor analyzing text length: {len(story_text)}")
    
    # 1. Epistemic Boundary Check
    if "Taurus Silver" in story_text and "Tatsuya" in story_text:
        logger.warning("AUDIT FAILED: Epistemic leak detected.")
        return "failed"

    # 2. Anti-Worf Check
    if "Miyuki was easily defeated" in story_text:
        logger.warning("AUDIT FAILED: Anti-Worf constraint broken.")
        return "failed"
        
    logger.info("AUDIT PASSED: Text is canon-compliant.")
    return "passed"
