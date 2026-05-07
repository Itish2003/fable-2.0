import asyncio
import logging
from typing import Any, AsyncGenerator
from google.adk.workflow._base_node import BaseNode
from google.adk.agents.context import Context

from src.utils.chunking import chunk_text
from src.services.embedding_service import get_embedding
from src.state.lore_models import LoreEmbedding
from src.database import AsyncSessionLocal

logger = logging.getLogger("fable.lore_ingestion")

# Embeddings per Ollama round-trip. 16 keeps Ollama warm without
# overwhelming a typical local install; bump if your setup can take it.
INGEST_BATCH_SIZE = 16


class LoreIngestionNode(BaseNode):
    """
    ETL Worker Node for ingesting raw Light Novel manuscripts.

    Chunks the text, fetches local Ollama embeddings in parallel batches,
    and stores each batch in its own Postgres transaction so a transient
    embedding failure mid-volume doesn't abort persisted progress.
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
        raw_text = node_input.get("text", "")
        universe = node_input.get("universe", "unknown")
        volume = node_input.get("volume", "unknown")

        if not raw_text:
            yield {"status": "error", "message": "No text provided for ingestion."}
            return

        chunks = chunk_text(raw_text)
        total = len(chunks)

        yield {
            "status": "processing",
            "message": f"Chunked text into {total} pieces. Embedding in batches of {INGEST_BATCH_SIZE}...",
        }

        persisted = 0
        failed = 0

        for batch_start in range(0, total, INGEST_BATCH_SIZE):
            batch = chunks[batch_start : batch_start + INGEST_BATCH_SIZE]

            # Parallel embed; return_exceptions keeps the gather alive on
            # individual Ollama failures so one bad chunk doesn't kill
            # the whole batch.
            results = await asyncio.gather(
                *(get_embedding(c) for c in batch),
                return_exceptions=True,
            )

            async with AsyncSessionLocal() as db_session:
                for chunk, vector in zip(batch, results):
                    if isinstance(vector, BaseException):
                        failed += 1
                        logger.warning(
                            "lore_ingestion: embedding failed for chunk in %s/%s: %s",
                            universe,
                            volume,
                            vector,
                        )
                        continue
                    db_session.add(
                        LoreEmbedding(
                            universe=universe,
                            volume=volume,
                            chunk_text=chunk,
                            embedding=vector,
                        )
                    )
                    persisted += 1
                await db_session.commit()

            yield {
                "status": "processing",
                "message": f"Persisted {persisted}/{total} chunks (failed {failed})...",
            }

        yield {
            "status": "success",
            "message": (
                f"Successfully ingested {persisted}/{total} chunks for "
                f"{universe} - {volume} into pgvector (failed {failed})."
            ),
        }
