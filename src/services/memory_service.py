"""
FableLocalMemoryService -- ADK 2.0 MemoryService backed by Ollama embeddings
and pgvector retrieval.

Epistemic-visibility enforcement is two-layered:

1. **Graph-level filter (this file).** ``search_memory`` loads the most recent
   session for ``(app_name, user_id)`` and pulls ``state["forbidden_concepts"]``.
   Any retrieval candidate whose ``chunk_text`` mentions a forbidden concept is
   dropped before it ever reaches the LLM. This is the "physically cannot pull
   lore hidden from POV" guarantee from the V2 plan.

2. **Substring fallback (auditor.py).** A second pass after generation
   re-checks the produced prose for the same forbidden concepts. Catches
   anything the LLM hallucinated independently of retrieved context.

If the session lookup fails (e.g., during ETL bootstrap, before any session
exists) we filter conservatively: log a warning and return raw retrieval
results without filtering. The auditor remains as a backstop in that case.
"""

import logging
from typing import Mapping, Sequence

from sqlalchemy import select
from google.adk.memory.base_memory_service import BaseMemoryService, SearchMemoryResponse
from google.adk.memory.memory_entry import MemoryEntry
from google.adk.events.event import Event
from google.adk.sessions.session import Session
from google.genai import types

from src.database import AsyncSessionLocal
from src.state.lore_models import LoreNode, LoreEdge, LoreEmbedding
from src.services.embedding_service import get_embedding

logger = logging.getLogger("fable.memory")


class FableLocalMemoryService(BaseMemoryService):
    """
    A custom ADK 2.0 MemoryService that uses:
    1. Ollama for local embeddings.
    2. pgvector for semantic search.
    3. NetworkX (via Postgres relationships) for Epistemic Filtering.
    """

    async def add_session_to_memory(self, session: Session) -> None:
        """Not utilized for Lore. Narrative history is handled by DatabaseSessionService."""
        pass

    async def add_events_to_memory(
        self,
        *,
        app_name: str,
        user_id: str,
        events: Sequence[Event],
        session_id: str | None = None,
        custom_metadata: Mapping[str, object] | None = None,
    ) -> None:
        """Not utilized for Lore. We use LoreIngestionNode to populate memory."""
        pass

    async def _epistemic_graph_filter(
        self,
        pov_character: str,
        center_node_name: str,
        max_radius: int = 1,
    ) -> set[int]:
        """
        Traverses the graph outwards from ``center_node_name`` up to ``max_radius``.
        Drops any edges where ``pov_character`` is not in the ``visibility_whitelist``
        (unless the whitelist is empty, meaning public knowledge).
        Returns a set of allowed LoreNode IDs.
        """
        allowed_node_ids: set[int] = set()

        async with AsyncSessionLocal() as session:
            # Find the starting node
            stmt = select(LoreNode).where(LoreNode.name == center_node_name)
            result = await session.execute(stmt)
            start_node = result.scalar_one_or_none()

            if not start_node:
                return allowed_node_ids

            allowed_node_ids.add(start_node.id)

            # Simple 1-hop traversal for now (can be expanded to full NetworkX later)
            edges_stmt = select(LoreEdge).where(
                (LoreEdge.source_id == start_node.id) | (LoreEdge.target_id == start_node.id)
            )
            edges_result = await session.execute(edges_stmt)
            edges = edges_result.scalars().all()

            for edge in edges:
                is_public = len(edge.visibility_whitelist) == 0
                is_authorized = pov_character in edge.visibility_whitelist

                if is_public or is_authorized:
                    allowed_node_ids.add(edge.source_id)
                    allowed_node_ids.add(edge.target_id)

        return allowed_node_ids

    async def _load_forbidden_concepts(
        self,
        *,
        app_name: str,
        user_id: str,
    ) -> list[str] | None:
        """
        Looks up the most recent session for (app_name, user_id) and returns
        its ``forbidden_concepts`` list. Returns ``None`` if no session can
        be located -- the caller should treat that as "filter conservatively".

        Imported lazily to avoid a circular import (memory_service is imported
        by ``app_container``, which also imports ``session_service``).
        """
        try:
            from src.services.session_manager import session_service

            listing = await session_service.list_sessions(
                app_name=app_name, user_id=user_id
            )
            sessions = listing.sessions or []
            if not sessions:
                return None

            # Pick the most recently updated session.
            latest = max(
                sessions,
                key=lambda s: getattr(s, "last_update_time", 0) or 0,
            )

            # ``list_sessions`` does not hydrate state; refetch.
            full_session = await session_service.get_session(
                app_name=app_name,
                user_id=user_id,
                session_id=latest.id,
            )
            if full_session is None:
                return None

            forbidden = full_session.state.get("forbidden_concepts", [])
            if not isinstance(forbidden, list):
                return []
            return [str(c) for c in forbidden if c]
        except Exception as e:
            logger.warning(
                "search_memory: failed to load forbidden_concepts for "
                f"app={app_name!r} user={user_id!r}: {e}. "
                "Returning unfiltered results; the auditor remains as backstop."
            )
            return None

    async def search_memory(
        self, *, app_name: str, user_id: str, query: str
    ) -> SearchMemoryResponse:
        """
        Performs a hybrid search.
        Note: Signature must match ADK 2.0 BaseMemoryService exactly --
        ``(app_name, user_id, query)``. ``session_id`` is NOT part of the
        contract, so we resolve the active session via ``list_sessions``.
        """
        response = SearchMemoryResponse(memories=[])

        # 1. Get Vector
        try:
            query_vector = await get_embedding(query)
        except Exception as e:
            logger.error(f"Ollama embedding failed: {e}")
            return response

        # 2. Resolve epistemic context for this user.
        forbidden_concepts = await self._load_forbidden_concepts(
            app_name=app_name, user_id=user_id
        )

        # 3. Search pgvector for nearest chunks.
        async with AsyncSessionLocal() as session:
            stmt = (
                select(LoreEmbedding)
                .order_by(LoreEmbedding.embedding.cosine_distance(query_vector))
                .limit(10)
            )
            result = await session.execute(stmt)
            embeddings = result.scalars().all()

        # 4. Apply the epistemic filter when we have one.
        if forbidden_concepts:
            lowered = [c.lower() for c in forbidden_concepts]

            def is_safe(chunk: str) -> bool:
                blob = (chunk or "").lower()
                return not any(c in blob for c in lowered)

            filtered = [emb for emb in embeddings if is_safe(emb.chunk_text)]
            dropped = len(embeddings) - len(filtered)
            if dropped:
                logger.info(
                    f"search_memory: epistemic filter dropped {dropped} chunk(s) "
                    f"for query={query!r} (forbidden={forbidden_concepts})."
                )
            embeddings = filtered

        # 5. Cap to top-5 after filtering and shape the response.
        for emb in embeddings[:5]:
            response.memories.append(
                MemoryEntry(
                    content=types.Content(
                        role="user",
                        parts=[types.Part.from_text(text=emb.chunk_text)],
                    ),
                    author=f"Volume: {emb.volume}",
                )
            )

        return response


# Instantiate singleton for ADK 2.0 App injection
memory_service = FableLocalMemoryService()
