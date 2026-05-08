"""Lore Keeper: synthesizes the lore-hunter swarm output into the World Bible.

Phase C expands the schema to populate the full v1-aligned substrate:
canon timeline (with pressure scores + playbooks), per-character voice
profiles, power-origin technique catalogs, anti-Worf integrity floors,
and per-character knowledge-boundary limits. ``inject_lore_to_state``
writes every populated field into ``ctx.state``; the storyteller's
``before_model_callback`` reads them per turn for context injection.
"""
from __future__ import annotations

import logging
from typing import Any, AsyncGenerator, List

from pydantic import BaseModel, Field

from google.adk.workflow import node
from google.adk.agents.context import Context
from google.adk.agents.llm_agent import LlmAgent
from google.adk.events import Event, EventActions, RequestInput
from google.genai import types

logger = logging.getLogger("fable.lore_keeper")


# ---------------------------------------------------------------------------
# Output schemas
# Gemini structured-output rejects dict[str, T] (additionalProperties), so
# everything-with-a-name lives as a list of objects with a `name` field.
# inject_lore_to_state converts those into dicts when writing state.
# ---------------------------------------------------------------------------

class AntiWorfRule(BaseModel):
    character: str = Field(description="Character name, e.g. 'Tatsuya Shiba'")
    rule: str = Field(description="Minimum competence guarantee")


class CanonEventDraft(BaseModel):
    """Canon-source event the OC must engage with. Tier guides storyteller pressure."""
    event_id: str = Field(description="Stable id, e.g. 'lung_vs_undersiders'")
    name: str
    in_world_date: str = Field(default="")
    pressure_score: int = Field(default=0, ge=0, le=100)
    tier: str = Field(default="medium", description="mandatory / high / medium")
    playbook: str = Field(default="", description="Rich narrative beats describing how the event typically unfolds")


class CharacterVoiceDraft(BaseModel):
    """Per-character speech profile for dialogue fidelity."""
    character: str
    speech_patterns: str = Field(default="")
    vocabulary_level: str = Field(default="")
    verbal_tics: List[str] = Field(default_factory=list)
    topics_to_avoid: List[str] = Field(default_factory=list)
    example_dialogue: str = Field(default="")


class TechniqueDraft(BaseModel):
    name: str
    mechanics: str = Field(default="")
    cost: str = Field(default="")
    limitations: List[str] = Field(default_factory=list)


class PowerSourceDraft(BaseModel):
    name: str
    universe: str = Field(default="")
    canon_techniques: List[TechniqueDraft] = Field(default_factory=list)
    signature_moves: List[str] = Field(default_factory=list)
    combat_style: str = Field(default="")
    oc_current_mastery: str = Field(default="")
    weaknesses_and_counters: List[str] = Field(default_factory=list)


class CharacterIntegrityDraft(BaseModel):
    character: str
    minimum_competence: str = Field(default="")
    anti_worf_notes: str = Field(default="")


class CharacterKnowledgeLimitsDraft(BaseModel):
    character: str
    knows: List[str] = Field(default_factory=list)
    suspects: List[str] = Field(default_factory=list)
    doesnt_know: List[str] = Field(default_factory=list)


class LoreKeeperOutput(BaseModel):
    world_primer: str = Field(
        description="Markdown synthesis of the crossover (3-6 paragraphs)."
    )
    forbidden_concepts: List[str] = Field(default_factory=list)
    anti_worf_rules: List[AntiWorfRule] = Field(default_factory=list)
    # Phase C substrate
    canon_timeline_events: List[CanonEventDraft] = Field(
        default_factory=list,
        description="Sorted upcoming canon events with pressure tiers + playbooks.",
    )
    character_voices: List[CharacterVoiceDraft] = Field(
        default_factory=list,
        description="One entry per significant canon character that may speak.",
    )
    power_sources: List[PowerSourceDraft] = Field(
        default_factory=list,
        description="Power-origin catalog driving the OC's abilities.",
    )
    canon_character_integrity: List[CharacterIntegrityDraft] = Field(
        default_factory=list,
        description="Anti-Worf integrity floors for protected canon characters.",
    )
    meta_knowledge_forbidden: List[str] = Field(
        default_factory=list,
        description="World-meta facts no in-fic character can reference.",
    )
    character_knowledge_limits: List[CharacterKnowledgeLimitsDraft] = Field(
        default_factory=list,
        description="Per-character knows/suspects/doesnt_know lists.",
    )


class WorldBibleExtraction(BaseModel):
    forbidden_concepts: List[str] = Field(default_factory=list)
    anti_worf_rules: List[AntiWorfRule] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Lore Keeper Agent
# ---------------------------------------------------------------------------

def create_lore_keeper() -> LlmAgent:
    return LlmAgent(
        name="lore_keeper",
        description="Fuses raw wiki research into a structured World Bible for the Fable Engine.",
        model="gemini-3.1-flash-lite",
        output_schema=LoreKeeperOutput,
        output_key="lore_keeper_output",
        generate_content_config=types.GenerateContentConfig(
            response_mime_type="application/json"
        ),
        instruction="""
You are the Lore Keeper. You will receive an array of research summaries
produced by the Lore Hunter Swarm. Synthesize them into a structured
World Bible that the storyteller will use for years of canon-faithful
chapters.

Output a JSON object matching this schema EXACTLY (omit nothing, but
empty arrays are fine when truly nothing applies):

1. "world_primer" — A rich markdown document (3-6 paragraphs) covering
   the crossover setting, power-system rules, key canon events,
   factions, and how the protagonist's anomalous ability slots in.

2. "forbidden_concepts" — Specific secrets and future spoilers the
   protagonist MUST NOT reference yet. Be concrete.

3. "anti_worf_rules" — Quick competence guarantees:
   [{"character": "Tatsuya Shiba", "rule": "never loses a direct combat exchange"}]

4. "canon_timeline_events" — The 5-15 most important upcoming canon
   events the storyteller will need to engage with. Each:
     {event_id, name, in_world_date, pressure_score (0-100),
      tier ("mandatory"|"high"|"medium"), playbook (rich beats)}
   Sort by chronology. pressure_score reflects narrative urgency
   relative to the story's start date.

5. "character_voices" — Speech profiles for the 5-12 most likely-to-speak
   canon characters. Each:
     {character, speech_patterns, vocabulary_level,
      verbal_tics: [...], topics_to_avoid: [...], example_dialogue}

6. "power_sources" — One entry per origin-power the OC inherits or any
   canon-world power system that interacts with the OC's abilities. Each:
     {name, universe, canon_techniques: [{name, mechanics, cost,
     limitations: [...]}], signature_moves: [...], combat_style,
     oc_current_mastery, weaknesses_and_counters: [...]}
   Be MECHANICALLY specific in cost and limitations — the storyteller
   uses these to write "powers shown bound, not naked" beats.

7. "canon_character_integrity" — Per protected canon character:
     {character, minimum_competence (things they ALWAYS can do),
      anti_worf_notes (why they must not be cheaply diminished)}

8. "meta_knowledge_forbidden" — World-meta facts no in-fic character
   can reference (e.g. "the Entities are extraterrestrial supercomputers"
   in a Worm story).

9. "character_knowledge_limits" — Per character:
     {character, knows: [...], suspects: [...], doesnt_know: [...]}

Return ONLY the JSON object. No markdown fences, no commentary.
""",
    )


# ---------------------------------------------------------------------------
# Fallback Extractor (unchanged: covers only the minimal fields)
# ---------------------------------------------------------------------------

def create_fallback_extractor() -> LlmAgent:
    return LlmAgent(
        name="fallback_extractor",
        description="Explicitly extracts World Bible data from raw text when the primary agent fails.",
        model="gemini-3.1-flash-lite",
        output_schema=WorldBibleExtraction,
        output_key="world_bible_extraction",
        generate_content_config=types.GenerateContentConfig(response_mime_type="application/json"),
        instruction="""Extract the forbidden concepts and anti-worf rules from the provided text.
Output a JSON object with:
- "forbidden_concepts": list of strings
- "anti_worf_rules": list of objects, each with "character" and "rule" keys
""",
    )


@node(name="fallback_injector", rerun_on_resume=True)
async def fallback_injector(ctx: Context, node_input: Any) -> AsyncGenerator[Any, None]:
    """Injects the fallback-extractor output into state.

    Reads ``state.world_bible_extraction`` (written by the fallback
    extractor's output_key) directly. Re-validates into
    :class:`WorldBibleExtraction` so the typed surface lights up; on
    parse failure, leave state as-is and surface the existing primer
    text via HITL anyway.
    """
    logger.info("Applying fallback extraction...")

    interrupt_id = "setup_world_primer"
    if ctx.resume_inputs.get(interrupt_id):
        logger.info("User approved World Primer (Fallback path). Transitioning to Intent Router.")
        yield Event(actions=EventActions(route="success"))
        return

    raw = ctx.state.get("world_bible_extraction") or {}
    if raw:
        try:
            rules = raw.get("anti_worf_rules") or []
            if rules and isinstance(rules[0], dict):
                raw = dict(raw)
                raw["anti_worf_rules"] = [AntiWorfRule(**r) for r in rules]
            wb = WorldBibleExtraction(**raw)
            ctx.state["forbidden_concepts"] = wb.forbidden_concepts
            ctx.state["anti_worf_rules"] = {r.character: r.rule for r in wb.anti_worf_rules}
            logger.info(
                "Fallback extraction applied: %d forbidden, %d anti-worf rules.",
                len(wb.forbidden_concepts), len(wb.anti_worf_rules),
            )
        except Exception as e:
            logger.warning("WorldBibleExtraction re-validation failed: %s", e)

    if ctx.state.get("last_story_text"):
        logger.info("Fallback: mid-story enrichment, auto-routing to success.")
        yield Event(actions=EventActions(route="success"))
        return

    primer_text = ctx.state.get("temp:crossover_primer", "World Primer Synthesis Complete (Fallback).")
    yield RequestInput(interrupt_id=interrupt_id, message=primer_text)


# ---------------------------------------------------------------------------
# State Injection Node
# ---------------------------------------------------------------------------

def _extract_universes_from_drafts(output: LoreKeeperOutput) -> list[str]:
    """Pull universe titles from power_sources[*].universe so Phase G's
    leakage scan has the canonical list. Deduplicates while preserving
    the order that mentions arrived in.
    """
    seen: list[str] = []
    seen_lower: set[str] = set()
    for s in output.power_sources or []:
        u = (getattr(s, "universe", "") or "").strip()
        if not u:
            continue
        key = u.lower()
        if key not in seen_lower:
            seen_lower.add(key)
            seen.append(u)
    return seen


def _write_substrate(ctx: Context, output: LoreKeeperOutput) -> None:
    """Write every Phase C substrate field into ctx.state.

    The drafts (lists with `character`/`name` fields) get converted to the
    runtime shape (Dict[str, T] for char-keyed maps, lists for everything
    else). Empty lists fall through and leave the state's default-empty
    structures in place — enrichment turns can replace them later.

    Also populates ``state.universes`` (Phase G) from the universes
    referenced in power_sources, so the leakage scan has the canonical
    list instead of falling back to substring heuristics.
    """
    universes = _extract_universes_from_drafts(output)
    if universes:
        ctx.state["universes"] = universes
    if output.canon_timeline_events:
        ctx.state["canon_timeline"] = {
            "events": [e.model_dump() for e in output.canon_timeline_events],
        }

    if output.character_voices:
        ctx.state["character_voices"] = {
            v.character: {
                "speech_patterns": v.speech_patterns,
                "vocabulary_level": v.vocabulary_level,
                "verbal_tics": v.verbal_tics,
                "topics_to_avoid": v.topics_to_avoid,
                "example_dialogue": v.example_dialogue,
            }
            for v in output.character_voices
        }

    if output.power_sources:
        ctx.state["power_origins"] = {
            "sources": [s.model_dump() for s in output.power_sources],
        }

    if output.canon_character_integrity:
        ctx.state["canon_character_integrity"] = {
            i.character: {
                "minimum_competence": i.minimum_competence,
                "anti_worf_notes": i.anti_worf_notes,
            }
            for i in output.canon_character_integrity
        }

    kb_raw = {
        "meta_knowledge_forbidden": list(output.meta_knowledge_forbidden or []),
        "character_knowledge_limits": {
            k.character: {
                "knows": k.knows,
                "suspects": k.suspects,
                "doesnt_know": k.doesnt_know,
            }
            for k in (output.character_knowledge_limits or [])
        },
    }
    if kb_raw["meta_knowledge_forbidden"] or kb_raw["character_knowledge_limits"]:
        ctx.state["knowledge_boundaries"] = kb_raw


@node(name="lore_keeper_injector", rerun_on_resume=True)
async def inject_lore_to_state(ctx: Context, node_input: Any) -> AsyncGenerator[Any, None]:
    """Apply the lore keeper's structured output into canonical state.

    Reads ``state.lore_keeper_output`` (written by the keeper's output_key)
    and re-validates it into :class:`LoreKeeperOutput` so the typed
    surface is available for the substrate writer. On any failure to
    surface a primer, route to the fallback extractor.
    """
    interrupt_id = "setup_world_primer"
    if ctx.resume_inputs.get(interrupt_id):
        logger.info("User approved World Primer. Transitioning to Intent Router.")
        yield Event(actions=EventActions(route="success"))
        return

    raw = ctx.state.get("lore_keeper_output") or {}
    if not raw or "world_primer" not in raw:
        logger.warning(
            "Lore Keeper produced no extractable output (state.lore_keeper_output=%r). "
            "Routing to fallback extractor.", type(raw).__name__,
        )
        yield Event(actions=EventActions(route="fallback"))
        return

    # Re-validate the parsed dict back into the Pydantic model so the
    # typed substrate-writer below works against attribute access.
    try:
        rules = raw.get("anti_worf_rules") or []
        if rules and isinstance(rules[0], dict):
            raw = dict(raw)
            raw["anti_worf_rules"] = [AntiWorfRule(**r) for r in rules]
        output = LoreKeeperOutput(**raw)
    except Exception as e:
        logger.warning(
            "LoreKeeperOutput re-validation failed: %s. Routing to fallback.", e,
        )
        yield Event(actions=EventActions(route="fallback"))
        return

    primer_text = output.world_primer
    ctx.state["forbidden_concepts"] = output.forbidden_concepts
    ctx.state["anti_worf_rules"] = {r.character: r.rule for r in output.anti_worf_rules}
    ctx.state["temp:crossover_primer"] = primer_text
    _write_substrate(ctx, output)

    logger.info(
        "Lore Keeper output injected: primer=%d chars, %d forbidden, %d anti-worf, "
        "%d timeline events, %d voices, %d power sources, %d integrity rules.",
        len(primer_text or ""),
        len(output.forbidden_concepts),
        len(output.anti_worf_rules),
        len(output.canon_timeline_events),
        len(output.character_voices),
        len(output.power_sources),
        len(output.canon_character_integrity),
    )

    if ctx.state.get("last_story_text"):
        logger.info("Mid-story enrichment complete. Auto-routing to success (no HITL).")
        yield Event(actions=EventActions(route="success"))
        return

    yield RequestInput(interrupt_id=interrupt_id, message=primer_text)
