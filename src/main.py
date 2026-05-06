import asyncio
import logging
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from src.database import init_db
from src.ws.manager import manager
from src.ws.runner import execute_adk_turn

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("fable.main")

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifecycle events for FastAPI."""
    logger.info("Initializing Fable 2.0 Database Schema...")
    await init_db()
    yield
    logger.info("Fable 2.0 Server shutting down...")

app = FastAPI(
    title="Fable 2.0 ADK Engine",
    description="Graph-based narrative simulation engine.",
    version="2.0.0",
    lifespan=lifespan
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], # For local testing
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class CreateStoryRequest(BaseModel):
    user_id: str = "local_tester" # Match frontend string

@app.post("/stories")
async def create_story(req: CreateStoryRequest):
    """
    Creates a new narrative session in the ADK Database.
    Returns the session_id to connect via WebSocket.
    """
    from src.services.session_manager import create_fable_session
    session_id = await create_fable_session(user_id=req.user_id)
    logger.info(f"New story session initialized in ADK: {session_id} for user {req.user_id}")
    return {"session_id": session_id}


@app.websocket("/ws/story/{session_id}")
async def story_websocket(websocket: WebSocket, session_id: str):
    """
    The primary real-time connection for the ADK 2.0 Workflow.
    """
    await manager.connect(websocket, session_id)
    try:
        # Upon initial connection, trigger the WorldBuilder setup node
        # ADK 2.0 Beta requires a new_message to start a root node traversal on a fresh session
        asyncio.create_task(execute_adk_turn(
            session_id=session_id,
            message_text="/start"
        ))
        
        while True:
            # Wait for client messages
            data = await websocket.receive_json()
            
            # Extract routing info
            interrupt_id = data.get("interrupt_id")
            resume_payload = data.get("resume_payload")
            message_text = data.get("message")
            
            # Fire and forget the ADK execution turn
            asyncio.create_task(
                execute_adk_turn(
                    session_id=session_id,
                    message_text=message_text,
                    resume_payload=resume_payload,
                    interrupt_id=interrupt_id
                )
            )
            
    except WebSocketDisconnect:
        manager.disconnect(session_id)
