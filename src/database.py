import os
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql+asyncpg://itish@localhost/fable")

# 1. Initialize the Engine for our local Lore tables (pgvector, NetworkX edges)
engine = create_async_engine(DATABASE_URL, echo=False)

# 2. Create the Session Maker
AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
)
