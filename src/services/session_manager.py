import asyncio
import os
from google.adk.sessions.database_session_service import DatabaseSessionService
from google.adk.platform import uuid as adk_uuid
from dotenv import load_dotenv

load_dotenv()

# We leverage the DATABASE_URL from our .env
# ADK 2.0 DatabaseSessionService handles its own SQLAlchemy engine initialization
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql+asyncpg://itish@localhost/fable2_0")

# 1. Initialize the ADK Session Service
# This service handles native ADK 2.0 session persistence, checkpoints, and event history.
# It expects a db_url string, not an engine object.
session_service = DatabaseSessionService(db_url=DATABASE_URL)

async def create_fable_session(user_id: str, parent_session_id: str = None) -> str:
    """
    Creates a new Fable session. 
    If parent_session_id is provided, it leverages ADK 2.0's native branching.
    """
    session_id = adk_uuid.new_uuid()
    await session_service.create_session(
        app_name="fable_2_0",
        user_id=user_id,
        session_id=session_id
    )
    # NOTE: ADK 2.0 DatabaseSessionService.create_session does NOT currently 
    # take parent_session_id as a direct argument in the base implementation.
    # We will need to handle branching via the Session object or custom extensions.
    return session_id
