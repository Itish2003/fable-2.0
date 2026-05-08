"""On-demand lore retrieval for the Storyteller.

Two entry points share one retrieval helper:

* ``retrieve_lore`` — internal coroutine returning structured chunks +
  parent ``LoreNode.attributes``. Used by the ``before_model_callback``
  in :mod:`src.nodes.storyteller` to pre-inject context for currently
  active characters.
* ``lore_lookup`` — ADK 2.0 tool exposed to the Storyteller LlmAgent so
  it can pull lore mid-generation (mode='AUTO').

Retrieval mirrors the established pgvector idiom in
``src.services.memory_service.search_memory`` —
``LoreEmbedding.embedding.cosine_distance(query_vector)`` ordered ascending
with ``limit(3)``. Do not invent a different shape.
"""

from __future__ import annotations

import logging

from google.adk.tools.tool_context import ToolContext
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from src.database import AsyncSessionLocal
from src.services.embedding_service import get_embedding
from src.state.lore_models import LoreEmbedding
from src.utils.sanitizer import sanitize_context

logger = logging.getLogger("fable.tools.lore_lookup")

TOP_K = 3


async def retrieve_lore(entity: str) -> list[dict]:
    """Vector-search the LoreEmbedding store for ``entity`` and return up to
    :data:`TOP_K` matches as JSON-serializable dicts.

    Each match has shape::

        {
            "chunk_text": str,
            "volume": str | None,
            "node_name": str | None,
            "node_type": str | None,
            "attributes": dict,
        }

    Returns ``[]`` if embedding fails or no rows match.
    """
    safe_entity = sanitize_context(entity)
    if not safe_entity:
        return []

    try:
        query_vector = await get_embedding(safe_entity)
    except Exception as e:
        logger.warning("retrieve_lore: embedding failed for %r: %s", safe_entity, e)
        return []

    async with AsyncSessionLocal() as session:
        stmt = (
            select(LoreEmbedding)
            .options(selectinload(LoreEmbedding.node))
            .order_by(LoreEmbedding.embedding.cosine_distance(query_vector))
            .limit(TOP_K)
        )
        result = await session.execute(stmt)
        embeddings = result.scalars().all()

    matches: list[dict] = []
    for emb in embeddings:
        node = emb.node
        matches.append(
            {
                "chunk_text": emb.chunk_text,
                "volume": emb.volume,
                "node_name": node.name if node else None,
                "node_type": node.node_type if node else None,
                "attributes": dict(node.attributes or {}) if node else {},
            }
        )

    return matches


async def lore_lookup(entity: str, tool_context: ToolContext) -> dict:
    """Look up canonical lore for a character, faction, location, or concept.

    Call this when you reference an entity whose details you are unsure of.
    The tool returns the top-3 most semantically similar chunks from the
    GraphRAG store along with their parent node attributes.

    Args:
        entity: The name of the character/faction/location/concept to look up.

    Returns:
        ``{"entity": <sanitized>, "matches": [...]}``. ``matches`` is empty
        when nothing similar is on file.
    """
    safe_entity = sanitize_context(entity)
    matches = await retrieve_lore(safe_entity)
    return {"entity": safe_entity, "matches": matches}
