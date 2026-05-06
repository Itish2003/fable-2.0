import asyncio
import logging
from typing import Mapping, Sequence
from collections.abc import AsyncIterator

from sqlalchemy import select, text
from google.adk.memory.base_memory_service import BaseMemoryService, SearchMemoryResponse
from google.adk.memory.memory_entry import MemoryEntry
from google.adk.events.event import Event
from google.adk.sessions.session import Session

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

    async def _epistemic_graph_filter(self, pov_character: str, center_node_name: str, max_radius: int = 1) -> set[int]:
        """
        Traverses the graph outwards from `center_node_name` up to `max_radius`.
        Drops any edges where `pov_character` is not in the `visibility_whitelist`
        (unless the whitelist is empty, meaning public knowledge).
        Returns a set of allowed LoreNode IDs.
        """
        allowed_node_ids = set()
        
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

    async def search_memory(
        self, *, app_name: str, user_id: str, query: str, custom_metadata: Mapping[str, object] = None
    ) -> SearchMemoryResponse:
        """
        Performs a hybrid search:
        1. Identifies the POV character and focus node from metadata.
        2. Gets the allowed node IDs via Epistemic Filtering.
        3. Generates the query embedding via Ollama.
        4. Queries pgvector using Cosine Distance (<=>), filtering by allowed nodes.
        """
        response = SearchMemoryResponse(memories=[])
        metadata = custom_metadata or {}
        
        pov_character = metadata.get("pov_character", "unknown")
        focus_node = metadata.get("focus_node", query) # Fallback to query if no explicit focus
        
        # 1. Epistemic Filter
        allowed_ids = await self._epistemic_graph_filter(pov_character, focus_node)
        
        # If the focus node doesn't exist, we fallback to a global search,
        # but in a strict Epistemic system, you might want to return empty.
        
        # 2. Get Vector
        try:
            query_vector = await get_embedding(query)
        except Exception as e:
            logger.error(f"Ollama embedding failed: {e}")
            return response
            
        # 3. Search pgvector
        async with AsyncSessionLocal() as session:
            # We use the <=> operator for cosine distance in pgvector
            # We filter by node_id in allowed_ids (or global context where node_id IS NULL)
            
            # SQL: SELECT chunk_text FROM lore_embeddings 
            # WHERE node_id IN (allowed_ids) OR node_id IS NULL 
            # ORDER BY embedding <=> query_vector LIMIT 5
            
            stmt = select(LoreEmbedding)
            
            if allowed_ids:
                stmt = stmt.where(
                    (LoreEmbedding.node_id.in_(allowed_ids)) | (LoreEmbedding.node_id.is_(None))
                )
                
            # Order by cosine distance (requires the pgvector extension and operator)
            # SQLAlchemy 2.0 + pgvector support:
            stmt = stmt.order_by(LoreEmbedding.embedding.cosine_distance(query_vector)).limit(5)
            
            result = await session.execute(stmt)
            embeddings = result.scalars().all()
            
            for emb in embeddings:
                response.memories.append(
                    MemoryEntry(
                        content=emb.chunk_text,
                        author=f"Volume: {emb.volume}",
                        timestamp=""
                    )
                )
                
        return response

# Instantiate singleton for ADK 2.0 App injection
memory_service = FableLocalMemoryService()
