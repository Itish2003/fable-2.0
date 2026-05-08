import logging
from typing import Any, List

from pydantic import BaseModel, Field
from google.genai import types

from google.adk.workflow import node
from google.adk.agents.context import Context
from google.adk.agents.llm_agent import LlmAgent
from google.adk.tools import google_search
from google.adk.tools.load_web_page import load_web_page

logger = logging.getLogger("fable.init_research")


# ---------------------------------------------------------------------------
# Output schemas
# ---------------------------------------------------------------------------

class ResearchTarget(BaseModel):
    entity: str = Field(
        description="Exact character, ability, faction, or power system name from the story premise"
    )
    query: str = Field(
        description="Precise Google search query targeting wiki or fandom sources for this entity"
    )
    focus: str = Field(
        description="What to extract: specific power mechanics, hard limitations, canon feats, relationships"
    )


class QueryPlan(BaseModel):
    targets: List[ResearchTarget] = Field(
        description="One entry per distinct named entity requiring canonical research"
    )


# ---------------------------------------------------------------------------
# 1. Query Planner Node
# Declarative output_schema + output_key. The structured QueryPlan is
# parsed by ADK and written to state.query_plan; the parser node below
# reads it directly without any defensive multi-path fallback.
# ---------------------------------------------------------------------------

def create_query_planner() -> LlmAgent:
    return LlmAgent(
        name="query_planner",
        description="Analyzes the Fable premise and produces a structured research plan.",
        model="gemini-3.1-flash-lite",
        output_schema=QueryPlan,
        output_key="query_plan",
        generate_content_config=types.GenerateContentConfig(
            response_mime_type="application/json"
        ),
        instruction="""
You are a Research Query Planner for a crossover fanfiction engine.

Analyze the story premise and identify EVERY named:
- Character (protagonist, antagonist, supporting cast, rivals)
- Ability, technique, or power system (e.g. "Limitless", "Ten Shadows")
- Faction, organization, or school
- Any source material that requires external research for canonical accuracy

For each entity produce a ResearchTarget:
- entity: the exact canonical name (e.g. "Satoru Gojo", "Tatsuya Shiba")
- query: a precise Google search query that will find wiki content
  (always include source title + entity + "wiki", e.g.
   "Jujutsu Kaisen Satoru Gojo fandom wiki abilities")
- focus: the specific information needed
  (e.g. "exact mechanics of Infinity, what can bypass it, stamina cost, canon feats")

Return a QueryPlan with a targets array. One target per entity. Be exhaustive.
""",
    )


# ---------------------------------------------------------------------------
# 2. Query Parser Node
# Reads state.query_plan (written by the planner's output_key) and
# converts it to the List[str] the parallel swarm fans out over.
# ---------------------------------------------------------------------------

@node(name="query_parser")
def parse_queries(ctx: Context, node_input: Any) -> List[str]:
    plan = ctx.state.get("query_plan") or {}
    targets = plan.get("targets") or []

    if not targets:
        premise = ctx.state.get("story_premise", "Fable Story")
        logger.warning(
            "Query Planner produced no targets (state.query_plan=%r). "
            "Using single premise fallback.", plan,
        )
        return [
            f"ENTITY: Unknown\nSEARCH QUERY: {premise} lore wiki\n"
            "EXTRACT: world rules, power systems, key characters"
        ]

    queries = [
        f"ENTITY: {t.get('entity', 'Unknown')}\n"
        f"SEARCH QUERY: {t.get('query', '')}\n"
        f"EXTRACT: {t.get('focus', '')}"
        for t in targets
        if isinstance(t, dict)
    ]
    logger.info("Query Planner produced %d targets.", len(queries))
    return queries


# ---------------------------------------------------------------------------
# 3. Lore Hunter Node (Tool Agent)
# ---------------------------------------------------------------------------
# NOTE: the previous in-line comment claiming output_schema is mutually
# exclusive with tools is wrong for ADK 2.0 -- _OutputSchemaRequestProcessor
# handles the combo via SetModelResponseTool. The lore_hunter still uses
# the free-form prose shape today because the keeper consumes prose; if
# the swarm output ever needs to be inspected per-entity, this is the
# place to add an output_schema=LoreFinding (low-risk follow-up).

def create_lore_hunter() -> LlmAgent:
    return LlmAgent(
        name="lore_hunter",
        description="Deep-scrapes wiki sources for one research target and returns canonical findings.",
        model="gemini-3.1-flash-lite",
        instruction="""
You are a Lore Hunter. You will receive a research target with three fields:
- ENTITY: the character, ability, or faction to research
- SEARCH QUERY: the exact Google search query to execute
- EXTRACT: what specific information to pull from the sources

Follow these steps EXACTLY. Do NOT skip or abbreviate any step.

STEP 1 — SEARCH:
Call google_search with the provided SEARCH QUERY.
From the results, identify the top 3 wiki URLs (prefer fandom.com, wikia.com, or official wikis).
Do NOT stop here — search snippets contain less than 5% of actual page content.

STEP 2 — SCRAPE (MANDATORY, NO EXCEPTIONS):
For EACH of the top 3 URLs, call load_web_page to fetch the full page content.
If a URL is inaccessible or errors, move to the next candidate.
You MUST successfully load at least 2 pages before synthesizing.
Using only search snippets without loading pages is a failure condition.

STEP 3 — SYNTHESIZE from scraped content (not snippets):
Write a detailed research summary covering everything relevant to EXTRACT:
- Exact ability/technique names and their precise mechanics step-by-step
- Hard limitations, costs, and conditions (what CANNOT be done, drawbacks, stamina)
- Power scaling: specific canonical feats with source citations
- Key relationships, allegiances, and hidden loyalties
- Timeline-critical events (mark future spoilers as [SPOILER])
- Any contradictions or ambiguities between sources

Be exhaustive. Every specific rule and limitation matters to the story engine.
End your summary with a list of successfully scraped URLs.
""",
        tools=[google_search, load_web_page],
        generate_content_config=types.GenerateContentConfig(
            tool_config=types.ToolConfig(
                include_server_side_tool_invocations=True
            )
        ),
    )
