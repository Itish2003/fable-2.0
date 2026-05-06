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
    Creates only the tables defined in our custom Lore models.
    ADK 2.0's DatabaseSessionService automatically manages its own session tables.
    """
    from src.state.lore_models import Base as LoreBase
    
    async with engine.begin() as conn:
        # Create Lore Engine Tables (Nodes, Edges, Embeddings, SourceText)
        await conn.run_sync(LoreBase.metadata.create_all)



