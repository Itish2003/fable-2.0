import asyncio
import logging
from typing import Optional, Dict, Any
from google.adk.events.request_input import RequestInput
from google.genai import types

from src.app_container import fable_runner
from src.ws.manager import manager
from google.adk.platform import uuid as adk_uuid

logger = logging.getLogger("fable.runner_loop")

async def execute_adk_turn(
    session_id: str, 
    user_id: str = "default_user",
    message_text: Optional[str] = None,
    resume_payload: Optional[Any] = None,
    interrupt_id: Optional[str] = None
):
    """
    Executes a single turn of the ADK 2.0 graph.
    Filters the Event stream and pushes updates via WebSockets.
    """
    
    run_kwargs = {
        "user_id": user_id,
        "session_id": session_id,
        # Generating a unique invocation ID per turn is good practice
        "invocation_id": adk_uuid.new_uuid(),
    }
    
    # 1. Prepare Input
    if message_text:
        # Standard input message (starts the graph or continues conversation)
        run_kwargs["new_message"] = types.Content(
            role="user", 
            parts=[types.Part.from_text(text=message_text)]
        )
    elif resume_payload and interrupt_id:
        # Resuming from a WorldBuilder RequestInput suspension
        # The ADK uses the invocation_context state to pass resume inputs. 
        # But for runner.run_async we can also trigger resumes by ensuring the payload matches.
        # ADK 2.0 uses 'state_delta' or internal event queues to resume RequestInputs. 
        # To handle RequestInput replies at the Runner level, we must provide it via `new_message`
        # mapped to the specific interruption, or use the runner's built-in resume features if available.
        # Actually, in ADK 2.0 Beta, we just pass the new_message and the runner matches it to the pending interrupt.
        # Alternatively, we can pass it via `state_delta` if the node looks for it in `ctx.resume_inputs`.
        # For our WorldBuilder, we fetch it via `ctx.resume_inputs.get(interrupt_id)`.
        
        # We will wrap it in a special message that ADK 2.0's HitlUtils maps, or inject to state delta.
        # For simplicity and adhering to ADK Beta mechanics, let's inject it into `state_delta` for now,
        # since our WorldBuilder manually checks `ctx.resume_inputs`.
        run_kwargs["state_delta"] = {
            f"_resume_{interrupt_id}": resume_payload  # Depending on exact ADK HITL implementation.
        }
        # In an actual pure ADK App, we would use Hitl utils, but we'll adapt to how our node works.
        pass
        
    try:
        # 2. Start the Async Generator Loop
        # Note: We must wrap the run_async call to cleanly catch standard exceptions
        generator = fable_runner.run_async(**run_kwargs)
        
        async for event in generator:
            
            # 3. Handle RequestInput (Suspension)
            if isinstance(event, RequestInput):
                logger.info(f"Graph Suspended by RequestInput: {event.interrupt_id}")
                await manager.send_personal_message({
                    "type": "request_input",
                    "interrupt_id": event.interrupt_id,
                    "message": event.message,
                    "response_schema": str(event.response_schema) if event.response_schema else None
                }, session_id)
                # Break the loop because the graph yields here until resumed
                break
                
            # 4. Handle Standard Events (Node Output)
            if hasattr(event, "content") and event.content and event.content.parts:
                text = event.content.parts[0].text
                author = getattr(event, "author", "system")
                
                if author == "storyteller":
                    # Stream the prose back to the client
                    await manager.send_personal_message({
                        "type": "text_delta",
                        "author": author,
                        "text": text
                    }, session_id)
                elif author == "archivist":
                    # The Archivist is silently mutating state
                    pass
            
            # 5. Handle Tool Calls
            if hasattr(event, "actions") and event.actions and event.actions.tool_calls:
                for tool_call in event.actions.tool_calls:
                    await manager.send_personal_message({
                        "type": "status",
                        "message": f"Writing to Lore Bible: {tool_call.name}..."
                    }, session_id)
                    
        # When generator is exhausted
        await manager.send_personal_message({
            "type": "turn_complete"
        }, session_id)
        
    except Exception as e:
        logger.error(f"Error during ADK turn execution: {e}")
        await manager.send_personal_message({
            "type": "error",
            "message": "The narrative weave destabilized. Please try again."
        }, session_id)
