import json
import logging
from typing import Any, List

from google.adk.workflow import node
from google.adk.agents.context import Context
from google.adk.events.event import Event
from google.adk.agents.llm_agent import LlmAgent
from google.adk.agents.llm_agent_config import LlmAgentConfig
from google.adk.tools.google_search_tool import GoogleSearchTool
from google.adk.tools.load_web_page import load_web_page

logger = logging.getLogger("fable.init_research")

# ---------------------------------------------------------------------------
# 1. Query Planner Node (LLM Agent)
# ---------------------------------------------------------------------------

def create_query_planner() -> LlmAgent:
    planner_config = LlmAgentConfig(
        name="query_planner",
        description="Analyzes the Fable premise and extracts necessary research queries.",
        model="gemini-3.1-flash-lite-preview",
        instruction="""
        You are a Research Query Planner.
        Analyze the user's story premise. Identify ANY concepts, character names, or powers 
        that need to be researched from external wikis to ensure canonical accuracy.
        
        OUTPUT FORMAT:
        Return ONLY a raw JSON array of strings representing Google search queries.
        Do not use markdown blocks. Do not add conversational text.
        
        Example:
        ["Jujutsu Kaisen Gojo Limitless technique mechanics", "Mahouka Tatsuya Shiba powerset"]
        """
    )
    return LlmAgent.from_config(planner_config, config_abs_path="")

# ---------------------------------------------------------------------------
# 2. JSON Array Parser Node
# ---------------------------------------------------------------------------
# The LLM outputs text. We need a fast Python node to cast it to an actual List
# so the ADK `parallel_worker=True` wrapper knows how to iterate over it.

@node(name="query_parser")
def parse_queries(ctx: Context, node_input: Any) -> List[str]:
    logger.info("Parsing Query Planner output...")
    text_output = ""
    try:
        if hasattr(node_input, "content") and node_input.content and node_input.content.parts:
            text_output = node_input.content.parts[0].text.strip()
            
            # Clean markdown if present
            if text_output.startswith("```json"):
                text_output = text_output.split("```json")[1].split("```")[0].strip()
            elif text_output.startswith("```"):
                text_output = text_output.split("```")[1].split("```")[0].strip()
                
            queries = json.loads(text_output)
            if isinstance(queries, list):
                logger.info(f"Generated {len(queries)} queries for the Swarm.")
                return queries
    except Exception as e:
        logger.error(f"Failed to parse Query Planner JSON: {e}. Output was: {text_output}")
    
    # Fallback
    premise = ctx.state.get("story_premise", "Fable Story")
    return [f"{premise} lore and worldbuilding"]


# ---------------------------------------------------------------------------
# 3. Lore Hunter Node (Tool Agent)
# ---------------------------------------------------------------------------

def create_lore_hunter() -> LlmAgent:
    hunter_config = LlmAgentConfig(
        name="lore_hunter",
        description="Executes a single search query and synthesizes the findings.",
        model="gemini-3.1-flash-lite-preview",
        instruction="""
        You are a Lore Hunter. You will receive a specific search query.
        1. Use the google_search tool to find high-quality wiki sources.
        2. Use load_web_page to read the actual wiki content if necessary.
        3. Output a detailed summary of the power mechanics, limitations, and character history found.
        Focus on specific rules and limitations that a Storyteller LLM would need to know.
        """
    )
    agent = LlmAgent.from_config(hunter_config, config_abs_path="")
    # Attach native ADK tools for web access
    agent.tools = [GoogleSearchTool(bypass_multi_tools_limit=True), load_web_page]
    return agent