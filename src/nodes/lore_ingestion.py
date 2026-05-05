from typing import Any, AsyncGenerator
from google.adk.workflow._base_node import BaseNode
from google.adk.agents.context import Context

from src.utils.chunking import chunk_text
from src.services.embedding_service import get_embedding
from src.state.lore_models import LoreEmbedding
from src.database import AsyncSessionLocal

class LoreIngestionNode(BaseNode):
    """
    ETL Worker Node for ingesting raw Light Novel manuscripts.
    Chunks the text, fetches local Ollama embeddings, and stores in Postgres (pgvector).
    """

    async def _run_impl(
        self,
        *,
        ctx: Context,
        node_input: dict[str, str],
    ) -> AsyncGenerator[dict[str, Any], None]:
        """
        node_input should contain:
        - 'text': The raw text of the manuscript.
        - 'universe': e.g., 'mahouka'
        - 'volume': e.g., 'Volume 01'
        """
        raw_text = node_input.get('text', '')
        universe = node_input.get('universe', 'unknown')
        volume = node_input.get('volume', 'unknown')

        if not raw_text:
            yield {"status": "error", "message": "No text provided for ingestion."}
            return

        chunks = chunk_text(raw_text)
        total_chunks = len(chunks)
        
        yield {"status": "processing", "message": f"Chunked text into {total_chunks} pieces. Generating embeddings..."}

        async with AsyncSessionLocal() as db_session:
            for i, chunk in enumerate(chunks):
                # Fetch local embedding via Ollama
                vector = await get_embedding(chunk)
                
                # Create the Postgres record
                lore_record = LoreEmbedding(
                    universe=universe,
                    volume=volume,
                    chunk_text=chunk,
                    embedding=vector
                )
                db_session.add(lore_record)
                
                if (i + 1) % 10 == 0:
                    yield {"status": "processing", "message": f"Processed {i + 1}/{total_chunks} chunks..."}

            # Commit the transaction
            await db_session.commit()

        yield {"status": "success", "message": f"Successfully ingested {total_chunks} chunks for {universe} - {volume} into pgvector."}
