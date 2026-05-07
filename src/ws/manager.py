from fastapi import WebSocket, WebSocketDisconnect
from typing import Dict, List
import logging
import asyncio

logger = logging.getLogger("fable.ws_manager")

class ConnectionManager:
    def __init__(self):
        # Maps session_id to active WebSocket connection
        self.active_connections: Dict[str, WebSocket] = {}
        # Track active ADK execution tasks to prevent race conditions during rewinds
        self.active_tasks: Dict[str, asyncio.Task] = {}

    async def connect(self, websocket: WebSocket, session_id: str):
        """Accept the connection and store the socket."""
        await websocket.accept()
        self.active_connections[session_id] = websocket
        logger.info(f"WebSocket connected for session: {session_id}")

    def disconnect(self, session_id: str):
        """Remove the connection from active pool."""
        if session_id in self.active_connections:
            del self.active_connections[session_id]
            self.cancel_active_task(session_id)
            logger.info(f"WebSocket disconnected for session: {session_id}")

    async def send_personal_message(self, message: dict, session_id: str):
        """Send a JSON payload to a specific session."""
        websocket = self.active_connections.get(session_id)
        if websocket:
            try:
                await websocket.send_json(message)
            except Exception as e:
                logger.error(f"Error sending message to {session_id}: {e}")

    def register_task(self, session_id: str, task: asyncio.Task):
        """Registers a background execution task for a session."""
        self.cancel_active_task(session_id)
        self.active_tasks[session_id] = task
        
    def cancel_active_task(self, session_id: str):
        """Cancels any currently running task for the session."""
        if session_id in self.active_tasks:
            task = self.active_tasks[session_id]
            if not task.done():
                logger.info(f"Cancelling active background task for session {session_id}")
                task.cancel()
            del self.active_tasks[session_id]

manager = ConnectionManager()