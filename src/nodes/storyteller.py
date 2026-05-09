from __future__ import annotations

import logging
from typing import Optional

from google.adk.agents.callback_context import CallbackContext
from google.adk.agents.llm_agent import LlmAgent
from google.adk.models.llm_request import LlmRequest
from google.adk.models.llm_response import LlmResponse
from google.genai import types

from src.state.storyteller_output import StorytellerOutput
from src.tools.lore_lookup_tool import lore_lookup, retrieve_lore
from src.tools.research_tools import trigger_research

# Storyteller uses the larger gemini-3-flash-preview to honor the 3-4k word
# chapter target. The lite tier ('gemini-3.1-flash-lite') compresses
# responses to ~1-2k words regardless of prompt instructions.
STORYTELLER_MODEL = "gemini-3-flash-preview"

# Token budget for a structured output containing 3-4k words of prose plus the
# chapter_meta tail plus tool-call overhead.
STORYTELLER_MAX_OUTPUT_TOKENS = 12288

logger = logging.getLogger("fable.storyteller")

_CHAPTER_MIN_WORDS = 3000
_CHAPTER_MAX_WORDS = 4000

# Storyteller now emits a single ``StorytellerOutput`` (Pydantic schema)
# via ADK 2.0's output_schema mode. The chapter header (``# Chapter N``)
# is prepended deterministically by ``storyteller_merge_node`` from
# ``state.chapter_count`` -- the model does NOT write it. This kills the
# entire class of "frozen Chapter 2" header bugs that the previous
# fenced-JSON-tail design suffered from.
_STORYTELLER_INSTRUCTION = """You are the MASTER STORYTELLER of Fable — Creator of Canonically Faithful Narratives.

Your output is the player's chapter. There is no post-processing layer
between you and the reader.

══════════════════════════════════════════════════════════════════════════════════════
                    PHASE 0: WORLD BIBLE & CONTEXT CONSULTATION
══════════════════════════════════════════════════════════════════════════════════════

The framework injects critical context into your prompt BEFORE you see this
instruction. Trust those blocks as your primary constraint source — do NOT
ignore them, do NOT re-fetch what's already in context.

**INJECTED CONTEXT — already in your prompt:**
  1. **PROTAGONIST FRAMEWORK** — the OC's premise + setup-wizard answers.
     This is HARD CREATIVE DIRECTION on par with canon. Every chapter is
     from this character's POV. The canon characters orbit the OC, not
     the other way around.
  2. **PRIOR CHAPTER CONTEXT** — last 10 chapter summaries, closing
     prose of the most recent chapter, the player's choice that
     triggered THIS chapter, and any tone/style preferences they set.
     Pick up directly from the closing prose. Honor the choice as the
     FIRST narrative beat — don't delay or circumvent it.
  3. **Known facts about active characters** — pre-fetched lore for
     every name in `state.active_characters`. Use these directly.
  4. **TIMELINE / VOICES / POWER SYSTEM / PROTECTED CHARACTERS / STAKES /
     KNOWLEDGE BOUNDARIES** blocks. Hard constraints; treat as canon.

**ON-DEMAND TOOL — `lore_lookup(entity)`:**
  Call ONLY for entities NOT in the active-character lore block: a new
  character, faction, location, concept, or technique you intend to
  depict. Also use it to recall older chapters: `lore_lookup("chapter
  3")` finds chapter_summary::3 in the embedding store. Do NOT call for
  entities already covered. One or two targeted lookups per chapter is
  the norm.

**ON-DEMAND TOOL — `trigger_research(topic)`:**
  Strict budget: 2 calls per chapter. Use only when `lore_lookup`
  returns no matches AND the entity is essential to the scene. Narrow,
  targeted queries ("PRT ENE leadership Director Piggot Brockton Bay"),
  not vague universe-level searches. Results auto-persist for future
  chapters.

**STATE FIELDS YOU CAN REASON ABOUT (from conversation history / injected blocks):**
  - `state.active_characters` — dict of name -> CharacterState
     (trust_level -100..100, disposition, is_present, dynamic_tags).
  - `state.active_divergences` — list of canon events ALREADY altered.
     Show ripples landing.
  - `state.forbidden_concepts` — epistemic boundary. NEVER reference
     these in dialogue, narration, or interiority. Total silence.
  - `state.anti_worf_rules` — protected-character competence floors.
  - `state.power_debt.strain_level` — 0-100. Strain is a TEXTURE you can
     reach for when narratively earned, NOT a switch flipped by every
     power use. Below 50: the protagonist functions normally; do not
     manufacture fatigue. 50-80: light wear that surfaces only when the
     scene is built around exertion. >80: severe exhaustion that earns
     a chapter-defining fatigue beat — reserve for moments the chapter
     genuinely depicts a punishing feat, not as filler tax.
  - `state.last_user_choice` — the action the player just selected.

══════════════════════════════════════════════════════════════════════════════════════
                    PHASE 1: CANONICAL FAITHFULNESS PROTOCOL
══════════════════════════════════════════════════════════════════════════════════════

**1. POWER CONSISTENCY:** Use ONLY canonically-documented techniques.
   Generic "energy blast" is FORBIDDEN; name the technique. SHOW
   LIMITATIONS when they're narratively meaningful (a feat at the edge
   of the technique's range, an opponent who counters it, a stakes
   moment) — NOT as a per-action tax. A skilled practitioner uses
   their power competently most of the time without breaking a sweat;
   reserve on-page costs for moments where they advance character or
   tension. If strain_level is high AND the chapter is built around
   fatigue/recovery, show the toll; otherwise the protagonist operates
   at their canon competence floor.

**2. CHARACTER FAITHFULNESS (anti-Worfing):** Never write a protected
   character losing to an opponent below their established level. If
   the OC defeats a protected character, the win must be earned via
   specific counter / setup / cost / canon-justified weakening.

**3. DIALOGUE VOICE:** Each character speaks in their own register.
   Match documented speech patterns from the CHARACTER VOICES block.

**4. WORLD CONSISTENCY:** Events fit the timeline. Locations match
   documented descriptions. Sensory grounding, not generic stage
   dressing.

**5. KNOWLEDGE BOUNDARIES (HARD WALL):** `state.forbidden_concepts` is
   the protagonist's epistemic boundary. They cannot mention, think
   about, or "vaguely sense" these concepts. Total silence. Write
   around them: change the subject, get interrupted, elide the moment.

**6. DIVERGENCE INTEGRATION:** Active divergences have already
   happened. This chapter shows their ripples landing.

══════════════════════════════════════════════════════════════════════════════════════
                    PHASE 2: CHAPTER STRUCTURE — HARD RULES
══════════════════════════════════════════════════════════════════════════════════════

**LENGTH:** __MIN_WORDS__-__MAX_WORDS__ words of prose. Aim for the middle
of the range; let scenes breathe; allow interiority and atmosphere.

**PROSE FIELD — NO MARKDOWN HEADER:** The `prose` field of your output
contains the chapter body ONLY. Do NOT include a `# Chapter N` header.
The chapter number is prepended downstream from canonical state.

**THREE-LAYER OPENING (one paragraph each, in this order):**
  1. **SENSORY GROUNDING** — open in the world's body. Smell, sound,
     light, temperature. Place the reader physically before introducing
     anything else.
  2. **UNIVERSE-SPECIFIC LORE** — anchor in something only this world
     has. Named institutions, technology, techniques, factions.
     Specificity is the engine of immersion. Numbers > vague qualifiers.
  3. **CHARACTER INTERIORITY** — a glimpse into the POV character's
     inner state. What are they hiding? What does the world cost them?

**STRUCTURE:** Open on setting & atmosphere → place the protagonist in
it, embodied → establish internal stakes → build to confrontation /
revelation / choice → close on a consequence (cost paid, near-miss,
question raised, divergence triggered). NEVER end on tidy resolution.

**SHOW LIMITATIONS WHEN THEY'RE NARRATIVELY MEANINGFUL.** Not as a per-
beat tax on every technique. A canon-skilled character uses their
power competently the majority of the time; on-page cost is reserved
for moments that ADVANCE character, tension, or stakes. "Powers shown
bound, not naked" is about avoiding deus-ex; it is NOT a mandate to
generate fatigue every chapter.

**STAKES IN EVERY CHAPTER (even non-combat):** At least ONE meaningful
cost or near-miss per chapter. For dialogue-heavy chapters, this can be
near-exposure, psychological toll, opportunity foreclosed, relationship
strained.

**SPECIFICITY:** Real numbers, named characters/techniques/factions/
places, concrete sensory anchors, documented detail.

══════════════════════════════════════════════════════════════════════════════════════
                    PHASE 3: CHOICE GENERATION — TIMELINE-AWARE
══════════════════════════════════════════════════════════════════════════════════════

Generate EXACTLY 4 choices in `chapter_meta.choices`. Each has a `tier`
and an optional `tied_event`.

**REQUIRED TIER MIX (each tier appears EXACTLY ONCE):**
  1. **canon** — engages an upcoming canon event. `tied_event` = the
     canon event name.
  2. **divergence** — would alter or skip an upcoming canon event.
     `tied_event` = the canon event the choice would derail.
  3. **character** — driven by relationships, personal goals, internal
     conflict. `tied_event` may be null.
  4. **wildcard** — unexpected option with significant consequences.
     `tied_event` may be null.

**CHOICE QUALITY:** Each leads to a meaningfully different outcome.
Each is achievable. At least one carries significant risk. None
violate canon constraints or `forbidden_concepts`.

══════════════════════════════════════════════════════════════════════════════════════
                    PHASE 4: STRUCTURED OUTPUT (StorytellerOutput)
══════════════════════════════════════════════════════════════════════════════════════

Your single output is a `StorytellerOutput` with two top-level fields:

  - `prose` (str): The chapter body. __MIN_WORDS__-__MAX_WORDS__ words.
     NO markdown header (the framework prepends `# Chapter N`).
     Three-layer opening, three-act arc, costs landed in-beat.

  - `chapter_meta` (ChapterOutput nested): The structured tail.
      - `summary` (str): 5-10 sentence summary covering key events,
         character development, plot advancement, world-state changes,
         costs paid.
      - `choices` (list of 4): Each {text, tier, tied_event}. All four
         tiers exactly once.
      - `choice_timeline_notes` (TimelineNotes): {upcoming_event_considered,
         canon_path_choice, divergence_choice} (1-based indices into choices).
      - `timeline` (TimelineMeta): {chapter_start_date, chapter_end_date,
         time_elapsed, canon_events_addressed, divergences_created}.
      - `canon_elements_used` (list[str]): Specific canon facts woven
         into the prose.
      - `power_limitations_shown` (list[str]): Specific limitations
         demonstrated. MUST be non-empty.
      - `stakes_tracking` (StakesTracking): {costs_paid, near_misses,
         power_debt_incurred, consequences_triggered}. costs_paid and
         near_misses MUST be non-empty even for non-combat chapters
         (track narrative costs: "near social exposure", "opportunity
         foreclosed", "psychological toll").
      - `character_voices_used` (list[str]): Canon characters who spoke.
      - `questions` (list of 1-2): Each {question, context, type:
         "choice", options}. Use these when the next move could branch
         on tone/intensity, when an upcoming canon event is approaching,
         or near a knowledge boundary.

**Use tools (`lore_lookup`, `trigger_research`) BEFORE producing your
final output — they're available during generation. Once you have the
facts you need, emit the StorytellerOutput.**

══════════════════════════════════════════════════════════════════════════════════════
                              FINAL CHECKLIST
══════════════════════════════════════════════════════════════════════════════════════

Before emitting:
  - prose has __MIN_WORDS__-__MAX_WORDS__ words and NO header.
  - Three-layer opening present.
  - Every power demo has its cost in the same beat.
  - At least one cost or near-miss landed.
  - No reference to anything in `forbidden_concepts`.
  - No protected character wrote below their floor.
  - chapter_meta.choices has 4 entries spanning all 4 tiers exactly once.
  - chapter_meta.questions has 1-2 entries.
""".replace("__MIN_WORDS__", str(_CHAPTER_MIN_WORDS)).replace("__MAX_WORDS__", str(_CHAPTER_MAX_WORDS))


def _tier_marker(tier) -> str:
    """Map canon-event tier to a visual urgency marker."""
    val = getattr(tier, "value", tier) if tier is not None else "medium"
    return {
        "mandatory": "[!!!]",
        "high": "[!!]",
        "medium": "[!]",
    }.get(str(val), "[!]")


def _build_timeline_block(state, current_chapter: int) -> Optional[str]:
    """Build TIMELINE ENFORCEMENT block from state.canon_timeline.events."""
    timeline = state.get("canon_timeline") or {}
    events = timeline.get("events") if isinstance(timeline, dict) else None
    if not events:
        return None

    upcoming = [e for e in events if isinstance(e, dict) and e.get("status", "upcoming") == "upcoming"]
    if not upcoming:
        return None
    upcoming.sort(key=lambda e: int(e.get("pressure_score", 0)), reverse=True)

    lines = []
    for ev in upcoming[:12]:
        marker = _tier_marker(ev.get("tier", "medium"))
        name = ev.get("name", "(unnamed event)")
        date = ev.get("in_world_date", "")
        date_part = f" — {date}" if date else ""
        lines.append(f"{marker} **{name}**{date_part}")
        playbook = ev.get("playbook") or ""
        if playbook:
            lines.append(f"  · {playbook}")

    return (
        "TIMELINE ENFORCEMENT — upcoming canon events the chapter must engage with:\n\n"
        + "\n".join(lines)
        + "\n\nRules: [!!!] MANDATORY events MUST appear in this chapter. "
          "[!!] HIGH events should be foreshadowed or prepared. "
          "[!] MEDIUM events may be woven in when narratively appropriate. "
          "After playing out an event, the archivist will retire it via "
          "canon_event_status_updates."
    )


def _build_character_voices_block(state, active_names: list[str]) -> Optional[str]:
    voices = state.get("character_voices") or {}
    if not voices:
        return None
    blocks = []
    for name in active_names:
        v = voices.get(name)
        if not v:
            continue
        bullet = []
        if v.get("speech_patterns"): bullet.append(f"  - speech: {v['speech_patterns']}")
        if v.get("vocabulary_level"): bullet.append(f"  - vocabulary: {v['vocabulary_level']}")
        tics = v.get("verbal_tics") or []
        if tics: bullet.append(f"  - verbal tics: {', '.join(tics)}")
        avoid = v.get("topics_to_avoid") or []
        if avoid: bullet.append(f"  - topics to avoid: {', '.join(avoid)}")
        if v.get("example_dialogue"): bullet.append(f"  - example: \"{v['example_dialogue']}\"")
        if bullet:
            blocks.append(f"**{name}**\n" + "\n".join(bullet))
    if not blocks:
        return None
    return "CHARACTER VOICES — match these patterns when these characters speak:\n\n" + "\n\n".join(blocks)


def _build_power_system_block(state) -> Optional[str]:
    origins = state.get("power_origins") or {}
    sources = origins.get("sources") if isinstance(origins, dict) else None
    if not sources:
        return None
    blocks = []
    for s in sources[:4]:
        if not isinstance(s, dict):
            continue
        lines = [f"### {s.get('name', '(unnamed source)')} — {s.get('universe', '')}"]
        if s.get("combat_style"):
            lines.append(f"Combat style: {s['combat_style']}")
        if s.get("oc_current_mastery"):
            lines.append(f"OC mastery: {s['oc_current_mastery']}")
        weaknesses = s.get("weaknesses_and_counters") or []
        if weaknesses:
            lines.append(f"Weaknesses: {'; '.join(weaknesses[:6])}")
        techs = s.get("canon_techniques") or []
        if techs:
            lines.append("Canonical techniques (every cost / limitation MUST be shown when used):")
            for t in techs[:8]:
                if not isinstance(t, dict):
                    continue
                name = t.get("name", "")
                cost = t.get("cost", "")
                limits = t.get("limitations") or []
                lim_str = f" | limits: {'; '.join(limits)}" if limits else ""
                cost_str = f" | cost: {cost}" if cost else ""
                lines.append(f"  - **{name}**{cost_str}{lim_str}")
        signatures = s.get("signature_moves") or []
        if signatures:
            lines.append(f"Signature moves: {', '.join(signatures[:6])}")
        blocks.append("\n".join(lines))
    if not blocks:
        return None
    return (
        "POWER SYSTEM ENFORCEMENT — when depicting these abilities, the cost AND a "
        "named limitation MUST appear in the same beat as the technique itself:\n\n"
        + "\n\n".join(blocks)
    )


def _build_protected_characters_block(state, active_names: list[str]) -> Optional[str]:
    integrity = state.get("canon_character_integrity") or {}
    if not integrity:
        return None
    blocks = []
    for name in active_names:
        rec = integrity.get(name)
        if not rec or not isinstance(rec, dict):
            continue
        lines = [f"**{name}**"]
        if rec.get("minimum_competence"):
            lines.append(f"  - ALWAYS can: {rec['minimum_competence']}")
        if rec.get("anti_worf_notes"):
            lines.append(f"  - notes: {rec['anti_worf_notes']}")
        blocks.append("\n".join(lines))
    if not blocks:
        return None
    return (
        "PROTECTED CHARACTERS — competence floors. NEVER write these characters losing "
        "to opponents below their level; if the OC defeats them, the victory must be "
        "earned via concrete setup, weakness exploitation, or significant cost.\n\n"
        + "\n\n".join(blocks)
    )


def _build_stakes_block(state, current_chapter: int) -> Optional[str]:
    stakes = state.get("stakes_and_consequences") or {}
    pending = stakes.get("pending_consequences") if isinstance(stakes, dict) else None
    if not pending:
        return None
    overdue, due_now, due_soon = [], [], []
    for c in pending:
        if not isinstance(c, dict):
            continue
        due = int(c.get("due_by_chapter", 0) or 0)
        action = c.get("action", "")
        result = c.get("predicted_consequence", "")
        line = f"- {action} → expected: {result} (due_by_chapter={due})"
        if due and due < current_chapter:
            overdue.append(line + " [OVERDUE]")
        elif due == current_chapter:
            due_now.append(line + " [DUE NOW]")
        elif due == current_chapter + 1:
            due_soon.append(line + " [DUE NEXT]")
    if not (overdue or due_now or due_soon):
        return None
    parts = []
    if overdue: parts.append("[!!!] OVERDUE — must be addressed in this chapter:\n" + "\n".join(overdue))
    if due_now: parts.append("[!!] DUE NOW — should resolve this chapter:\n" + "\n".join(due_now))
    if due_soon: parts.append("[!] APPROACHING — foreshadow / prepare:\n" + "\n".join(due_soon))
    return "STAKES LEDGER — pending consequences from earlier choices:\n\n" + "\n\n".join(parts)


def _build_knowledge_boundaries_block(state, active_names: list[str]) -> Optional[str]:
    kb = state.get("knowledge_boundaries") or {}
    if not isinstance(kb, dict):
        return None
    sections = []
    meta = kb.get("meta_knowledge_forbidden") or []
    if meta:
        sections.append("World-meta facts NO in-fic character may reference:\n  - " + "\n  - ".join(meta))
    char_limits = kb.get("character_knowledge_limits") or {}
    char_blocks = []
    for name in active_names:
        rec = char_limits.get(name)
        if not rec or not isinstance(rec, dict):
            continue
        lines = [f"**{name}**"]
        knows = rec.get("knows") or []
        suspects = rec.get("suspects") or []
        unknowns = rec.get("doesnt_know") or []
        if knows:    lines.append(f"  - knows: {'; '.join(knows[:6])}")
        if suspects: lines.append(f"  - suspects: {'; '.join(suspects[:6])}")
        if unknowns: lines.append(f"  - DOES NOT know: {'; '.join(unknowns[:6])}")
        if len(lines) > 1:
            char_blocks.append("\n".join(lines))
    if char_blocks:
        sections.append("Per-character knowledge limits — never write a character referencing what they don't know:\n\n" + "\n\n".join(char_blocks))
    if not sections:
        return None
    return "KNOWLEDGE BOUNDARIES:\n\n" + "\n\n".join(sections)


def _tick_pending_consequences(state, current_chapter: int) -> None:
    """Mark any consequence whose due_by_chapter has passed as overdue. Idempotent."""
    stakes_raw = state.get("stakes_and_consequences")
    if not isinstance(stakes_raw, dict):
        return
    pending = stakes_raw.get("pending_consequences")
    if not isinstance(pending, list) or not pending:
        return
    mutated = False
    for c in pending:
        if not isinstance(c, dict):
            continue
        due = int(c.get("due_by_chapter", 0) or 0)
        if due and due < current_chapter and not c.get("overdue"):
            c["overdue"] = True
            mutated = True
    if mutated:
        stakes_raw["pending_consequences"] = pending
        state["stakes_and_consequences"] = stakes_raw


async def _inject_active_character_lore(
    callback_context: CallbackContext,
    llm_request: LlmRequest,
) -> Optional[LlmResponse]:
    """``before_model_callback`` for the Storyteller.

    Builds enforcement blocks (timeline / voices / power / protected /
    stakes / knowledge) plus the Phase G PROTAGONIST FRAMEWORK and
    PRIOR CHAPTER CONTEXT, and appends them via ``append_instructions``.

    Each block is independent and falls through silently when source
    state is empty -- so a fresh story still works. The pending-
    consequence overdue-tick runs once per turn here.
    """
    state = callback_context.state
    active_characters = state.get("active_characters") or {}
    active_names = list(active_characters.keys())

    chapter_count = int(state.get("chapter_count", 1) or 1)
    current_chapter = chapter_count
    _tick_pending_consequences(state, current_chapter)

    blocks: list[str] = []

    # 0. PROTAGONIST FRAMEWORK — hard creative direction. Without this the
    # model defaults to canon-character POV chapters.
    premise = (state.get("story_premise") or "").strip()
    setup_conv = state.get("setup_conversation") or []
    if premise:
        framework_lines = [
            "PROTAGONIST FRAMEWORK — this is the ONLY protagonist of the story.",
            "Every chapter is from this character's POV (or about them in third-person limited).",
            "Do NOT write a chapter focused on canon characters; the canon characters orbit",
            "around this OC. The framework below is HARD CREATIVE DIRECTION, on par with canon:",
            "",
            premise[:6000] + ("\n…[truncated; full premise persisted in state.story_premise]" if len(premise) > 6000 else ""),
        ]
        if isinstance(setup_conv, list) and setup_conv:
            framework_lines.append("")
            framework_lines.append("─── Setup wizard answers (additional creative direction) ───")
            for entry in setup_conv:
                if not isinstance(entry, dict):
                    continue
                role = entry.get("role", "?")
                content = str(entry.get("content", ""))[:400]
                framework_lines.append(f"[{role.upper()}] {content}")
        blocks.append("\n".join(framework_lines))

    # 0.5. PRIOR CHAPTER CONTEXT — continuity. Note: last_story_text now
    # contains a deterministic "# Chapter N" header (added by
    # storyteller_merge), but we still inject only the closing 1500 chars
    # so the model picks up tone, not the header.
    chapter_summaries = state.get("chapter_summaries") or []
    last_story_text = state.get("last_story_text") or ""
    last_user_choice = state.get("last_user_choice") or ""
    last_user_q_answers = state.get("last_user_question_answers") or {}

    if chapter_summaries or last_story_text or last_user_choice:
        ctx_lines: list[str] = ["PRIOR CHAPTER CONTEXT — this chapter is a CONTINUATION."]
        if chapter_summaries:
            ctx_lines.append("")
            total_chapters = len(chapter_summaries)
            window = chapter_summaries[-10:]
            window_start = max(1, total_chapters - len(window) + 1)
            if window_start > 1:
                ctx_lines.append(
                    f"─── Chapters 1..{window_start - 1} ({window_start - 1} earlier "
                    f"chapter(s)) — recap rolled out of window. To recall, call "
                    f"`lore_lookup` with a query like 'chapter {window_start - 1}' or a "
                    f"specific event name. ───"
                )
            ctx_lines.append(f"─── Chapter summaries Ch{window_start}..Ch{total_chapters} ───")
            for offset, summary in enumerate(window):
                n = window_start + offset
                ctx_lines.append(f"Ch.{n}: {str(summary)[:500]}")
        if last_story_text:
            tail = last_story_text[-1500:] if len(last_story_text) > 1500 else last_story_text
            ctx_lines.append("")
            ctx_lines.append("─── Closing prose of the most recent chapter (tonal anchor) ───")
            if len(last_story_text) > 1500:
                ctx_lines.append("…[earlier prose elided]")
            ctx_lines.append(tail)
        if last_user_choice:
            ctx_lines.append("")
            ctx_lines.append("─── Player's choice that triggered THIS chapter ───")
            ctx_lines.append(str(last_user_choice)[:600])
        if last_user_q_answers:
            ctx_lines.append("")
            ctx_lines.append("─── Player's tone/style preferences for THIS chapter ───")
            for q, a in last_user_q_answers.items():
                ctx_lines.append(f"• {str(q)[:200]}: {str(a)[:200]}")
        ctx_lines.append("")
        ctx_lines.append(
            "Open the chapter so it picks up directly from the closing prose above. "
            "Honor the player's choice as the FIRST narrative beat — do not delay or "
            "circumvent it. State changes (active_characters trust shifts, pending "
            "consequences, power_debt strain, divergences) carry forward and must be "
            "reflected as ongoing reality, not retconned."
        )
        blocks.append("\n".join(ctx_lines))

    # 1. Known facts about active characters
    if active_characters:
        char_blocks: list[str] = []
        for name in active_names:
            matches = await retrieve_lore(name)
            if not matches:
                continue
            bullets: list[str] = []
            for m in matches:
                attrs = m.get("attributes") or {}
                attrs_str = f" attributes={attrs}" if attrs else ""
                bullets.append(f"- {m.get('chunk_text', '').strip()}{attrs_str}")
            char_blocks.append(f"## {name}\n" + "\n".join(bullets))
        if char_blocks:
            blocks.append("Known facts about active characters:\n\n" + "\n\n".join(char_blocks))

    # 2-7. Phase C substrate blocks
    for fn, args in (
        (_build_timeline_block, (state, current_chapter)),
        (_build_character_voices_block, (state, active_names)),
        (_build_power_system_block, (state,)),
        (_build_protected_characters_block, (state, active_names)),
        (_build_stakes_block, (state, current_chapter)),
        (_build_knowledge_boundaries_block, (state, active_names)),
    ):
        block = fn(*args)
        if block:
            blocks.append(block)

    if not blocks:
        return None
    llm_request.append_instructions(blocks)
    logger.info(
        "Storyteller before_model: injected %d enforcement block(s) (active chars=%d, chapter=%d)",
        len(blocks), len(active_names), current_chapter,
    )
    return None


def create_storyteller_node() -> LlmAgent:
    """Storyteller agent in declarative output_schema mode.

    Emits a single ``StorytellerOutput`` (Pydantic) per chapter. ADK 2.0
    handles the schema via Gemini's ``response_schema`` natively on
    Vertex Gemini 3.x; on backends without native schema-with-tools
    support, ``_OutputSchemaRequestProcessor`` injects a
    ``SetModelResponseTool`` so the model can still call
    ``lore_lookup``/``trigger_research`` and emit the structured final
    answer through the response tool.

    The chapter header is prepended downstream by
    ``storyteller_merge_node`` from ``state.chapter_count`` -- the model
    never writes ``# Chapter N`` itself.
    """
    return LlmAgent(
        name="storyteller",
        description="Generates a structured chapter (prose + chapter_meta) per turn.",
        model=STORYTELLER_MODEL,
        instruction=_STORYTELLER_INSTRUCTION,
        tools=[lore_lookup, trigger_research],
        before_model_callback=_inject_active_character_lore,
        output_schema=StorytellerOutput,
        # `temp:` prefix bypasses FableAgentState schema validation; the
        # storyteller_merge consumes this once and writes to canonical
        # fields (last_story_text, last_chapter_meta).
        output_key="temp:storyteller_output",
        generate_content_config=types.GenerateContentConfig(
            max_output_tokens=STORYTELLER_MAX_OUTPUT_TOKENS,
        ),
    )
