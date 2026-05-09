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
from src.state.lore_models import LoreEmbedding, LoreNode
from src.utils.canon_aliases import resolve_alias
from src.utils.sanitizer import sanitize_context

logger = logging.getLogger("fable.tools.lore_lookup")

TOP_K = 3

# Cosine-distance ceiling for retrieve_lore. pgvector's cosine_distance is
# 1 - cosine_similarity for normalised vectors, so MAX_DISTANCE = 0.4 means
# "keep only matches with cosine_similarity >= 0.6". Without this filter,
# a query for an unknown entity (e.g. "Saegusa Mayumi" before B1 backfill)
# returns the nearest neighbour regardless of how poor the match is -- the
# model trusts the function-call result and gets misled by junk. Returning
# `[]` for below-threshold queries lets the model fall back to its training.
MAX_DISTANCE = 0.4

# Minimum chunk_text length to be considered a "substantive" retrieval result.
# Empirically, the Ollama embedding model produces vectors for short text
# (e.g. archivist_runtime shells like "Shiba Miyuki {}") that cluster at
# unnaturally low cosine distance (~0.111) to any query, regardless of
# semantic relevance. These shells outrank legitimate Vol XX canon chunks
# (~0.37 distance for genuine matches) and dominate retrieval. Enforcing a
# minimum length filters these out -- canon chunks are 200-500+ chars and
# easily pass; runtime shells are ~16 chars and fail. Adjust upward if even
# longer noise patterns emerge.
MIN_CHUNK_LENGTH = 60


async def retrieve_lore(entity: str) -> list[dict]:
    """Vector-search the LoreEmbedding store for ``entity`` and return up to
    :data:`TOP_K` matches whose cosine_distance is below :data:`MAX_DISTANCE`.

    Each match has shape::

        {
            "chunk_text": str,
            "volume": str | None,
            "node_name": str | None,
            "node_type": str | None,
            "attributes": dict,
        }

    Returns ``[]`` if embedding fails, no rows match, or all returned rows
    are below the similarity threshold.
    """
    safe_entity = sanitize_context(entity)
    if not safe_entity:
        return []

    try:
        query_vector = await get_embedding(safe_entity)
    except Exception as e:
        logger.warning("retrieve_lore: embedding failed for %r: %s", safe_entity, e)
        return []

    distance_expr = LoreEmbedding.embedding.cosine_distance(query_vector)

    # ENTITY-FIRST RETRIEVAL: if the query resolves to a canonical character,
    # prefer chunks linked to that entity's node (ranked by cosine distance
    # within the entity's chunks). This unlocks the canon corpus -- a bare
    # name query like "Tatsuya Shiba" doesn't have strong embedding affinity
    # to canon prose like "He stared at his sister with analytical
    # detachment", but the entity link tells us those chunks are ABOUT
    # Tatsuya regardless. We still rank by cosine within the entity's
    # chunk set so query-relevant prose surfaces first.
    canonical = resolve_alias(safe_entity)
    if canonical is not None:
        async with AsyncSessionLocal() as session:
            node_stmt = select(LoreNode.id).where(LoreNode.name == canonical)
            node_id = (await session.execute(node_stmt)).scalar_one_or_none()
            if node_id is None:
                # Try existing-name forms that resolve to the same canonical
                # (handles the duplicate situation pre-Phase-C dedupe).
                all_nodes = (await session.execute(select(LoreNode.id, LoreNode.name))).all()
                for nid, nname in all_nodes:
                    if resolve_alias(nname) == canonical:
                        node_id = nid
                        break
            if node_id is not None:
                # Fetch entity-linked chunks ranked by cosine to the query.
                # The threshold is RELAXED here (0.6 instead of 0.4) because
                # we already have entity certainty from the node link; cosine
                # is just for in-entity ranking, not for membership filtering.
                stmt = (
                    select(LoreEmbedding, distance_expr.label("distance"))
                    .options(selectinload(LoreEmbedding.node))
                    .where(LoreEmbedding.node_id == node_id)
                    .order_by(distance_expr)
                    .limit(TOP_K * 4)
                )
                rows = (await session.execute(stmt)).all()
                matches: list[dict] = []
                for emb, distance in rows:
                    chunk = emb.chunk_text or ""
                    if len(chunk) < MIN_CHUNK_LENGTH:
                        continue
                    node = emb.node
                    matches.append(
                        {
                            "chunk_text": chunk,
                            "volume": emb.volume,
                            "node_name": node.name if node else None,
                            "node_type": node.node_type if node else None,
                            "attributes": dict(node.attributes or {}) if node else {},
                        }
                    )
                    if len(matches) >= TOP_K:
                        break
                if matches:
                    logger.info(
                        "retrieve_lore(%r): entity-linked path returned %d/%d (canonical=%r, node_id=%d)",
                        safe_entity, len(matches), len(rows), canonical, node_id,
                    )
                    return matches

    # COSINE FALLBACK: query isn't a known entity (or no chunks linked yet).
    # Fall back to global cosine search with both threshold filters.
    async with AsyncSessionLocal() as session:
        # Over-fetch (4x TOP_K) so we still hit TOP_K substantive matches
        # after filtering out noise shells whose embedding artifact ranks
        # them top regardless of similarity.
        stmt = (
            select(LoreEmbedding, distance_expr.label("distance"))
            .options(selectinload(LoreEmbedding.node))
            .order_by(distance_expr)
            .limit(TOP_K * 4)
        )
        result = await session.execute(stmt)
        rows = result.all()

    matches: list[dict] = []
    skipped_distance = 0
    skipped_short = 0
    for emb, distance in rows:
        if distance is not None and distance > MAX_DISTANCE:
            skipped_distance += 1
            continue
        chunk = emb.chunk_text or ""
        if len(chunk) < MIN_CHUNK_LENGTH:
            skipped_short += 1
            continue
        node = emb.node
        matches.append(
            {
                "chunk_text": chunk,
                "volume": emb.volume,
                "node_name": node.name if node else None,
                "node_type": node.node_type if node else None,
                "attributes": dict(node.attributes or {}) if node else {},
            }
        )
        if len(matches) >= TOP_K:
            break
    if skipped_distance or skipped_short:
        logger.info(
            "retrieve_lore(%r): cosine fallback scanned %d, skipped %d distant, %d short, returning %d",
            safe_entity, len(rows), skipped_distance, skipped_short, len(matches),
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
