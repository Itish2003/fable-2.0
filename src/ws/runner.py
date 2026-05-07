import asyncio
import logging
from typing import Optional, Dict, Any
from google.adk.events.request_input import RequestInput
from google.genai import types

from src.app_container import fable_runner
from src.ws.manager import manager
from google.adk.platform import uuid as adk_uuid
from google.adk.workflow.utils._workflow_hitl_utils import (
    create_request_input_response,
    has_request_input_function_call,
    get_request_input_interrupt_ids
)

logger = logging.getLogger("fable.runner_loop")

async def execute_adk_turn(
    session_id: str, 
    user_id: str = "local_tester",
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
        "invocation_id": adk_uuid.new_uuid(),
    }
    
    logger.info(f"Executing turn for App: {fable_runner.app_name}, Session: {session_id}, User: {user_id}")
    
    # 1. Prepare Input
    if message_text and message_text != "/start":
        run_kwargs["new_message"] = types.Content(
            role="user", 
            parts=[types.Part.from_text(text=message_text)]
        )
    elif message_text == "/start":
        run_kwargs["new_message"] = types.Content(
            role="user", 
            parts=[types.Part.from_text(text="[System: Begin Simulation]")]
        )
    elif resume_payload and interrupt_id:
        run_kwargs["new_message"] = types.Content(
            role="user",
            parts=[create_request_input_response(
                interrupt_id=interrupt_id,
                response={"payload": resume_payload}
            )]
        )
        
    try:
        generator = fable_runner.run_async(**run_kwargs)
        
        async for event in generator:
            
            # 3. Handle RequestInput (Suspension) natively via ADK utils
            if has_request_input_function_call(event):
                interrupt_ids = get_request_input_interrupt_ids(event)
                req_interrupt_id = interrupt_ids[0] if interrupt_ids else "unknown"
                
                # Extract the prompt message from the function call arguments
                req_message = "Please provide input."
                if event.content and event.content.parts:
                    for part in event.content.parts:
                        if part.function_call and part.function_call.id == req_interrupt_id:
                            req_message = part.function_call.args.get("message", req_message)
                            break
                            
                logger.info(f"Graph Suspended by RequestInput: {req_interrupt_id}")
                await manager.send_personal_message({
                    "type": "request_input",
                    "interrupt_id": req_interrupt_id,
                    "message": req_message,
                }, session_id)
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
            # ADK Beta actions can be dicts or objects, so we safely check
            actions = getattr(event, "actions", None)
            if actions:
                tool_calls = getattr(actions, "tool_calls", None)
                if not tool_calls and isinstance(actions, dict):
                    tool_calls = actions.get("tool_calls", None)
                    
                if tool_calls:
                    # tool_calls can be a list of dicts or objects
                    for tool_call in tool_calls:
                        name = getattr(tool_call, "name", None)
                        if not name and isinstance(tool_call, dict):
                            name = tool_call.get("name", "tool")
                            
                        await manager.send_personal_message({
                            "type": "status",
                            "message": f"Writing to Lore Bible: {name}..."
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
