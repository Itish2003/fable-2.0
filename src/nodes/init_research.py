import logging
from typing import Any, List

from pydantic import BaseModel, Field
from google.genai import types

from google.adk.workflow import node
from google.adk.agents.context import Context
from google.adk.agents.llm_agent import LlmAgent
from google.adk.tools import google_search
from google.adk.tools.load_web_page import load_web_page

from src.state.lore_finding import LoreFinding

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
        # `temp:` prefix bypasses FableAgentState schema validation
        # (ADK sessions/state.py:39-40). The query plan is transient --
        # parse_queries consumes it once and converts to the swarm's
        # input list. No need to persist as long-term session state.
        output_key="temp:query_plan",
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
    plan = ctx.state.get("temp:query_plan") or {}
    targets = plan.get("targets") or []

    if not targets:
        premise = ctx.state.get("story_premise", "Fable Story")
        logger.warning(
            "Query Planner produced no targets (state.temp:query_plan=%r). "
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
# 3. Lore Hunter Node (Tool Agent + structured output)
# ---------------------------------------------------------------------------
# ADK 2.0 supports tools + output_schema simultaneously via
# _OutputSchemaRequestProcessor (verified in installed package). The hunter
# scrapes the web with google_search + load_web_page, then emits a single
# LoreFinding describing the entity researched.
#
# IMPORTANT: do NOT set output_key on this agent. _ParallelWorker fans out
# this same agent N times under different sub-branches; output_key would
# write to the SAME state field on every parallel run, last-writer-wins
# (per audit: workflow/_llm_agent_wrapper.py:101-102). The aggregated
# list flows through the output channel via _ParallelWorker._run_impl,
# which is what the keeper reads. State has no role here.

def create_lore_hunter() -> LlmAgent:
    return LlmAgent(
        name="lore_hunter",
        description="Deep-scrapes wiki sources for one research target; emits a structured LoreFinding.",
        model="gemini-3.1-flash-lite",
        output_schema=LoreFinding,
        # Deliberately NO output_key (parallel_worker last-writer-wins footgun).
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

STEP 3 — EMIT a single LoreFinding describing what you found:

- ``entity_name``: the canonical name from the EXTRACT target.
- ``entity_type``: one of "character", "ability", "faction", "event", "world",
  or "other". Pick the closest fit; use "other" if uncertain.
- ``summary``: a 2-4 sentence synthesis of the most important canonical
  facts. The keeper aggregates these across the swarm.

Depending on entity_type, populate the relevant fields. Empty containers
are fine for irrelevant axes — the keeper treats empty as "no data".

For abilities / power systems:
  ``canon_techniques`` (list of {name, mechanics, cost, limitations}),
  ``weaknesses_and_counters``, ``combat_style``.
  Be MECHANICALLY specific in mechanics + cost + limitations. The
  storyteller uses these to write "powers shown bound, not naked" beats.

For characters:
  ``speech_patterns``, ``vocabulary_level``, ``verbal_tics``,
  ``topics_to_avoid``, ``example_dialogue`` — voice profile.
  ``minimum_competence`` — what this character ALWAYS can do (anti-Worf floor).
  ``knows`` / ``suspects`` / ``doesnt_know`` — epistemic limits.

For canon events:
  ``in_world_date``, ``pressure_score`` (0-100 narrative urgency),
  ``tier`` ("mandatory" / "high" / "medium"), ``playbook`` (rich beats).

Universal:
  ``spoilers`` — future-knowledge facts the OC must NOT reference yet.
  ``sources`` — URLs you successfully scraped.
  ``research_query`` — echo back the SEARCH QUERY you were given
     (provenance for the keeper).

Be exhaustive within the relevant fields. Every specific rule and
limitation matters to the story engine. Do NOT include free-form prose
outside the schema — the structured fields ARE your output.
""",
        tools=[google_search, load_web_page],
        generate_content_config=types.GenerateContentConfig(
            tool_config=types.ToolConfig(
                include_server_side_tool_invocations=True
            )
        ),
    )
