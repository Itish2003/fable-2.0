import logging
from typing import Any, AsyncGenerator

from google.adk.workflow import node
from google.adk.agents.context import Context
from google.adk.events.event_actions import EventActions
from google.adk.events.event import Event

from src.state.models import FableAgentState

logger = logging.getLogger("fable.enrich_analyzer")

@node(name="enrich_analyzer_node")
async def enrich_analyzer_node(ctx: Context, node_input: Any) -> AsyncGenerator[Any, None]:
    """
    Scans ctx.state to check if it's sparsely populated (e.g., fewer than 3 characters).
    If gaps are found, yields an EventActions(route="enrich") to send the graph back to Phase 8 LoreHunterSwarm.
    """
    # Try parsing the hot state
    try:
        state = FableAgentState(**{k: ctx.state[k] for k in ctx.state._value.keys() | ctx.state._delta.keys()})
    except Exception:
        state = FableAgentState()

    active_chars = state.active_characters
    forbidden_concepts = state.forbidden_concepts

    needs_enrichment = False
    enrichment_queries = []

    if len(active_chars) < 3:
        needs_enrichment = True
        enrichment_queries.append("lore about major factions and key characters")
    
    if len(forbidden_concepts) < 2:
        needs_enrichment = True
        enrichment_queries.append("secret lore and forbidden concepts")

    if needs_enrichment:
        logger.info(f"State is sparse. Routing to enrich. Queries: {enrichment_queries}")
        # Store the queries so query_planner or lore_hunter can pick them up in Phase 8
        ctx.state["enrichment_queries"] = enrichment_queries
        yield EventActions(route="enrich")
    else:
        logger.info("State is well-populated. Routing to story.")
        yield EventActions(route="story")
