import logging
from typing import Any, AsyncGenerator, List, Dict

from pydantic import BaseModel, Field

from google.adk.workflow import node
from google.adk.agents.context import Context
from google.adk.agents.llm_agent import LlmAgent
from google.adk.events import Event, EventActions, RequestInput
from google.genai import types

logger = logging.getLogger("fable.lore_keeper")


# ---------------------------------------------------------------------------
# Output schemas
# Dict[str, str] generates additionalProperties which Gemini rejects.
# Use a typed list of objects instead and convert to dict when writing state.
# ---------------------------------------------------------------------------

class AntiWorfRule(BaseModel):
    character: str = Field(description="Character name, e.g. 'Tatsuya Shiba'")
    rule: str = Field(description="Minimum competence guarantee, e.g. 'never loses a direct combat'")


class LoreKeeperOutput(BaseModel):
    world_primer: str = Field(
        description="Human-readable markdown synthesis of all crossover rules, "
                    "power limitations, key factions, and canon constraints."
    )
    forbidden_concepts: List[str] = Field(
        default_factory=list,
        description="Secrets and future spoilers the protagonist MUST NOT know yet."
    )
    anti_worf_rules: List[AntiWorfRule] = Field(
        default_factory=list,
        description="Per-character minimum competence guarantees."
    )


class WorldBibleExtraction(BaseModel):
    forbidden_concepts: List[str] = Field(
        default_factory=list,
        description="Secrets and spoilers the protagonist MUST NOT know."
    )
    anti_worf_rules: List[AntiWorfRule] = Field(
        default_factory=list,
        description="Baseline competence rules for major characters."
    )


# ---------------------------------------------------------------------------
# Lore Keeper Agent
# ---------------------------------------------------------------------------

def create_lore_keeper() -> LlmAgent:
    return LlmAgent(
        name="lore_keeper",
        description="Fuses raw wiki research into a structured World Bible for the Fable Engine.",
        model="gemini-3.1-flash-lite-preview",
        instruction="""
You are the Lore Keeper. You will receive an array of research summaries
produced by the Lore Hunter Swarm.

Your job is to synthesize everything into a structured World Bible.

Output a JSON object with exactly these three fields:

1. "world_primer" — A rich markdown document (3-6 paragraphs) covering:
   - The crossover setting and power-system rules
   - Key canon events, factions, and relationships
   - How the protagonist's anomalous ability interacts with this world

2. "forbidden_concepts" — A list of strings. Each is a secret, future spoiler,
   or piece of knowledge the protagonist does NOT yet have. Be specific.
   Example: ["Tatsuya is the legendary Mahesvara", "Miyuki's limiter exists"]

3. "anti_worf_rules" — A list of objects, each with "character" and "rule" keys.
   This prevents key characters from being humiliated in the narrative.
   Example: [{"character": "Tatsuya Shiba", "rule": "never loses a direct combat exchange"}]

Return ONLY the JSON object. No markdown fences, no extra commentary.
""",
        output_schema=LoreKeeperOutput,
        generate_content_config=types.GenerateContentConfig(
            response_mime_type="application/json"
        ),
    )


# ---------------------------------------------------------------------------
# Fallback Extractor
# ---------------------------------------------------------------------------

def create_fallback_extractor() -> LlmAgent:
    return LlmAgent(
        name="fallback_extractor",
        description="Explicitly extracts World Bible data from raw text when the primary agent fails.",
        model="gemini-3.1-flash-lite-preview",
        instruction="""Extract the forbidden concepts and anti-worf rules from the provided text.
Output a JSON object with:
- "forbidden_concepts": list of strings
- "anti_worf_rules": list of objects, each with "character" and "rule" keys
""",
        output_schema=WorldBibleExtraction,
        generate_content_config=types.GenerateContentConfig(response_mime_type="application/json")
    )


@node(name="fallback_injector", rerun_on_resume=True)
async def fallback_injector(ctx: Context, node_input: Any) -> AsyncGenerator[Any, None]:
    """Injects the explicitly extracted JSON into the state."""
    logger.info("Applying fallback extraction...")

    interrupt_id = "setup_world_primer"
    if ctx.resume_inputs.get(interrupt_id):
        logger.info("User approved World Primer (Fallback path). Transitioning to Intent Router.")
        yield Event(actions=EventActions(route="success"))
        return

    def _apply_fallback(wb: WorldBibleExtraction) -> None:
        ctx.state["forbidden_concepts"] = wb.forbidden_concepts
        ctx.state["anti_worf_rules"] = {r.character: r.rule for r in wb.anti_worf_rules}
        logger.info("Successfully populated state via fallback extractor.")

    def _try_fallback_dict(d: dict) -> None:
        try:
            raw_rules = d.get("anti_worf_rules", [])
            if raw_rules and isinstance(raw_rules[0], dict):
                d = dict(d)
                d["anti_worf_rules"] = [AntiWorfRule(**r) for r in raw_rules]
            _apply_fallback(WorldBibleExtraction(**d))
        except Exception as e:
            logger.debug("Dict→WorldBibleExtraction failed: %s", e)

    out = getattr(node_input, "output", None)
    if isinstance(out, WorldBibleExtraction):
        _apply_fallback(out)
    elif isinstance(out, dict):
        _try_fallback_dict(out)
    elif isinstance(node_input, dict):
        _try_fallback_dict(node_input)

    primer_text = ctx.state.get("temp:crossover_primer", "World Primer Synthesis Complete (Fallback).")
    yield RequestInput(interrupt_id=interrupt_id, message=primer_text)


# ---------------------------------------------------------------------------
# State Injection Node
# ---------------------------------------------------------------------------

@node(name="lore_keeper_injector", rerun_on_resume=True)
async def inject_lore_to_state(ctx: Context, node_input: Any) -> AsyncGenerator[Any, None]:
    """
    Extracts LoreKeeperOutput from node_input, stores forbidden_concepts and
    anti_worf_rules into state, then suspends for user primer review.
    """
    # Check resume FIRST. On resume, node_input is the adk_request_input response
    # (Content), not the lore_keeper output. Extraction already ran before suspend.
    interrupt_id = "setup_world_primer"
    if ctx.resume_inputs.get(interrupt_id):
        logger.info("User approved World Primer. Transitioning to Intent Router.")
        yield Event(actions=EventActions(route="success"))
        return

    primer_text = None

    def _apply_structured(output: LoreKeeperOutput) -> None:
        nonlocal primer_text
        primer_text = output.world_primer
        ctx.state["forbidden_concepts"] = output.forbidden_concepts
        ctx.state["anti_worf_rules"] = {r.character: r.rule for r in output.anti_worf_rules}
        ctx.state["temp:crossover_primer"] = primer_text
        logger.info("Lore Keeper structured output injected into state.")

    def _try_from_dict(d: dict) -> bool:
        """Try to build LoreKeeperOutput from a plain dict (ADK workflow wraps output_schema as dict)."""
        try:
            raw_rules = d.get("anti_worf_rules", [])
            if raw_rules and isinstance(raw_rules[0], dict):
                d = dict(d)
                d["anti_worf_rules"] = [AntiWorfRule(**r) for r in raw_rules]
            output = LoreKeeperOutput(**d)
            _apply_structured(output)
            return True
        except Exception as e:
            logger.debug("Dict→LoreKeeperOutput failed: %s", e)
            return False

    # ── Path 1a: Pydantic model on .output ────────────────────────────────
    out = getattr(node_input, "output", None)
    if isinstance(out, LoreKeeperOutput):
        _apply_structured(out)

    # ── Path 1b: ADK workflow passes output_schema result as plain dict ───
    elif isinstance(out, dict) and "world_primer" in out:
        _try_from_dict(out)

    # ── Path 1c: node_input itself is the dict ────────────────────────────
    elif isinstance(node_input, dict) and "world_primer" in node_input:
        _try_from_dict(node_input)

    # ── Path 2: raw text content ──────────────────────────────────────────
    elif getattr(node_input, "content", None):
        for part in (node_input.content.parts or []):
            text = getattr(part, "text", None)
            if text:
                primer_text = text
                ctx.state["temp:crossover_primer"] = primer_text
                logger.info("Lore Keeper raw text content injected into state.")
                break

    # ── Path 3: nothing useful — route to fallback extractor ──────────────
    if not primer_text:
        logger.warning(
            "Lore Keeper produced no extractable output (node_input type=%s). "
            "Routing to fallback extractor.",
            type(node_input).__name__,
        )
        yield Event(actions=EventActions(route="fallback"))
        return

    # ── HITL: suspend for user review ─────────────────────────────────────
    yield RequestInput(interrupt_id=interrupt_id, message=primer_text)
