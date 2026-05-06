import os
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql+asyncpg://itish@localhost/fable2_0")

# 1. Initialize the Engine for our local Lore tables (pgvector, NetworkX edges)
engine = create_async_engine(DATABASE_URL, echo=False)

# 2. Create the Session Maker
AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
)

async def init_db():
    """
    Initializes the database schema.
    Creates all tables defined in our models and ADK models.
    """
    from src.state.lore_models import Base as LoreBase
    from google.adk.sessions.schemas.v1 import Base as AdkBase
    from sqlalchemy import text
    
    async with engine.begin() as conn:
        # Create Lore Engine Tables
        await conn.run_sync(LoreBase.metadata.create_all)
        # Create ADK Session Management Tables
        await conn.run_sync(AdkBase.metadata.create_all)
        
        # Manually insert the schema version into adk_internal_metadata
        # ADK 2.0 Beta requires this record to exist if the table exists.
        await conn.execute(text(
            "INSERT INTO adk_internal_metadata (\"key\", value) "
            "VALUES ('schema_version', '1') "
            "ON CONFLICT (\"key\") DO NOTHING;"
        ))



