from typing import Any, AsyncGenerator
from google.adk.workflow import node
from google.adk.agents.context import Context
from google.adk.events.request_input import RequestInput
from google.adk.events.event import Event
from google.adk.platform import uuid

import logging

logger = logging.getLogger("fable.worldbuilder")

@node(name="world_builder", rerun_on_resume=True)
async def run_world_builder(
    ctx: Context,
    node_input: Any,
) -> AsyncGenerator[Any, None]:
    """
    Interactive Node for setting up a new story.
    Uses RequestInput to pause the workflow and ask the user for setup parameters.
    """
    state_key = "world_builder_state"
    builder_state = ctx.state.get(state_key, {"step": "genre"})
    
    # Check if we are resuming from a previous RequestInput
    interrupt_id = f"setup_{builder_state['step']}"
    resume_payload = ctx.resume_inputs.get(interrupt_id)
    
    if builder_state["step"] == "genre":
        if not resume_payload:
            # We haven't asked the user yet. Yield RequestInput and suspend.
            yield RequestInput(
                interrupt_id=interrupt_id,
                message="Welcome to Fable 2.0. What genre or existing universe would you like to explore?",
            )
            return
        else:
            # We received the answer
            logger.info(f"User selected universe: {resume_payload}")
            ctx.state["target_universe"] = resume_payload
            builder_state["step"] = "protagonist"
            ctx.state[state_key] = builder_state
            
    if builder_state["step"] == "protagonist":
        interrupt_id = f"setup_{builder_state['step']}"
        resume_payload = ctx.resume_inputs.get(interrupt_id)
        
        if not resume_payload:
            yield RequestInput(
                interrupt_id=interrupt_id,
                message="Excellent. Please describe your protagonist's core ability or anomaly.",
            )
            return
        else:
            logger.info(f"User protagonist defined: {resume_payload}")
            ctx.state["protagonist_ability"] = resume_payload
            builder_state["step"] = "complete"
            ctx.state[state_key] = builder_state
            
    if builder_state["step"] == "complete":
        # The setup is done. We can now initialize the FableAgentState and 
        # yield a signal that routes the graph to the main narrative engine.
        logger.info("World Building Complete. Initializing State...")
        
        # We return a specific routing dictionary that the Graph edges can follow
        yield {
            "setup_status": "complete",
            "universe": ctx.state.get("target_universe"),
            "protagonist": ctx.state.get("protagonist_ability")
        }
