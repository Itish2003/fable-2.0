import json
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
# output_schema is safe here because query_planner has no tools.
# ---------------------------------------------------------------------------

def create_query_planner() -> LlmAgent:
    return LlmAgent(
        name="query_planner",
        description="Analyzes the Fable premise and produces a structured research plan.",
        model="gemini-3.1-flash-lite",
        output_schema=QueryPlan,
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
# Converts QueryPlan structured output into the List[str] the parallel swarm needs.
# ---------------------------------------------------------------------------

@node(name="query_parser")
def parse_queries(ctx: Context, node_input: Any) -> List[str]:
    logger.info("Parsing Query Planner output...")

    def _targets_to_queries(targets: list) -> List[str]:
        out = []
        for t in targets:
            if isinstance(t, ResearchTarget):
                out.append(f"ENTITY: {t.entity}\nSEARCH QUERY: {t.query}\nEXTRACT: {t.focus}")
            elif isinstance(t, dict):
                out.append(
                    f"ENTITY: {t.get('entity', 'Unknown')}\n"
                    f"SEARCH QUERY: {t.get('query', '')}\n"
                    f"EXTRACT: {t.get('focus', '')}"
                )
        return out

    def _parse_plan_dict(d: dict) -> List[str] | None:
        """Handle QueryPlan dict: {targets: [...]} or bare list."""
        if "targets" in d:
            return _targets_to_queries(d["targets"])
        return None

    # Path 1a: Pydantic model on .output
    out = getattr(node_input, "output", None)
    if isinstance(out, QueryPlan):
        queries = _targets_to_queries(out.targets)
        logger.info("Query Planner structured output: %d targets.", len(queries))
        return queries

    # Path 1b: ADK workflow passes output_schema result as plain dict on .output
    if isinstance(out, dict):
        queries = _parse_plan_dict(out)
        if queries:
            logger.info("Query Planner dict output: %d targets.", len(queries))
            return queries

    # Path 1c: node_input itself is the dict (some ADK workflow wrappers)
    if isinstance(node_input, dict):
        queries = _parse_plan_dict(node_input)
        if queries:
            logger.info("Query Planner raw dict node_input: %d targets.", len(queries))
            return queries

    # Path 2: raw text content
    text_output = ""
    try:
        content = getattr(node_input, "content", None)
        if content and getattr(content, "parts", None):
            text_output = content.parts[0].text.strip()
            if text_output.startswith("```json"):
                text_output = text_output.split("```json")[1].split("```")[0].strip()
            elif text_output.startswith("```"):
                text_output = text_output.split("```")[1].split("```")[0].strip()
            parsed = json.loads(text_output)
            if isinstance(parsed, list):
                logger.info("Query Planner text fallback (list): %d queries.", len(parsed))
                return parsed
            if isinstance(parsed, dict):
                queries = _parse_plan_dict(parsed)
                if queries:
                    logger.info("Query Planner text fallback (dict): %d targets.", len(queries))
                    return queries
    except Exception as e:
        logger.error("Failed to parse Query Planner output: %s. Raw: %s", e, text_output)

    premise = ctx.state.get("story_premise", "Fable Story")
    logger.warning("Query Planner produced no parseable output. Using single premise fallback.")
    return [f"ENTITY: Unknown\nSEARCH QUERY: {premise} lore wiki\nEXTRACT: world rules, power systems, key characters"]


# ---------------------------------------------------------------------------
# 3. Lore Hunter Node (Tool Agent)
# ---------------------------------------------------------------------------
# IMPORTANT: output_schema is MUTUALLY EXCLUSIVE with tools in ADK 2.0.
# (Field docs: "when output_schema is set, agent can ONLY reply and CANNOT
# use any tools.") The lore_hunter MUST use tools to scrape content, so it
# outputs rich prose. The lore_keeper (no tools) synthesizes the structure.

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
