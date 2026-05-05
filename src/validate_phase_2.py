import asyncio
import os
import sys

# Ensure project root is in path for imports
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from src.state.lore_models import Base, LoreEmbedding
from src.database import engine, AsyncSessionLocal
from src.nodes.lore_ingestion import LoreIngestionNode
from google.adk.agents.context import Context
from sqlalchemy import select

async def setup_db():
    print("Initializing Database Schema for Lore Models...")
    async with engine.begin() as conn:
        # Create all tables (if they don't exist)
        await conn.run_sync(Base.metadata.create_all)
    print("Schema initialized.")

async def validate_phase_2():
    print("\n--- PHASE 2 VALIDATION ---")
    
    await setup_db()

    # 1. Prepare Dummy Data
    dummy_text = """
    Tatsuya Shiba walked through the corridors of First High School. He maintained his usual
    impassive expression, calculating the security vectors of the building. His sister, Miyuki,
    walked beside him, drawing the attention of every student they passed.

    In the distance, Mayumi Saegusa watched them with a mix of curiosity and amusement. She 
    knew there was more to the irregular student than met the eye, though the exact nature 
    of his abilities remained a mystery to the Student Council.
    """

    print("\n[1/3] Instantiating LoreIngestionNode...")
    ingestion_node = LoreIngestionNode(name="lore_ingestion_worker")
    
    from unittest.mock import MagicMock
    
    # Mock a Context for the NodeRunner
    ctx = MagicMock()

    print("\n[2/3] Running ETL Pipeline (Chunking -> Ollama Embedding -> pgvector)...")
    try:
        # Execute the generator
        agen = ingestion_node._run_impl(
            ctx=ctx,
            node_input={
                "text": dummy_text,
                "universe": "mahouka",
                "volume": "Volume 01 - Test"
            }
        )
        
        async for event in agen:
            print(f"  -> {event['status'].upper()}: {event['message']}")
            
        print("\n✓ LoreIngestionNode completed successfully.")
    except Exception as e:
        print(f"\n✗ LoreIngestionNode failed: {e}")
        import traceback
        traceback.print_exc()
        return

    # 3. Verify Database
    print("\n[3/3] Verifying pgvector storage...")
    try:
        async with AsyncSessionLocal() as session:
            stmt = select(LoreEmbedding).where(LoreEmbedding.volume == "Volume 01 - Test")
            result = await session.execute(stmt)
            embeddings = result.scalars().all()
            
            if len(embeddings) > 0:
                print(f"✓ Found {len(embeddings)} semantic chunks securely stored in pgvector.")
                # Print the dimension of the first vector to confirm it's populated
                print(f"  -> Vector dimensions: {len(embeddings[0].embedding)}")
            else:
                print("✗ No embeddings found in database after ingestion.")
    except Exception as e:
        print(f"✗ Verification failed: {e}")

    print("\n--- VALIDATION COMPLETE ---")

if __name__ == "__main__":
    asyncio.run(validate_phase_2())
