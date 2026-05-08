from __future__ import annotations

import logging
from typing import Optional

from google.adk.agents.callback_context import CallbackContext
from google.adk.agents.llm_agent import LlmAgent
from google.adk.models.llm_request import LlmRequest
from google.adk.models.llm_response import LlmResponse
from google.genai import types

from src.tools.lore_lookup_tool import lore_lookup, retrieve_lore
from src.tools.research_tools import trigger_research

# We use the highly efficient gemini-3.1-flash-lite model as requested
STORYTELLER_MODEL = "gemini-3.1-flash-lite"

# Token budget for an 8,000-word chapter + JSON tail + tool-call overhead.
# Sourced from FableWeaver v1's settings.storyteller_max_output_tokens
# (/Users/itish/Downloads/Fable/src/config.py:29). 8,000 words ≈ 12,000
# tokens of prose; the remainder covers the structured tail and any
# lore_lookup tool-call round-trips.
STORYTELLER_MAX_OUTPUT_TOKENS = 24576

logger = logging.getLogger("fable.storyteller")


# Ported from FableWeaver v1's narrative.py instruction (Phases 0-4) and
# adapted to v2 state field names and v2's idiomatic ADK 2.0 plumbing:
#   * dynamic per-turn context (active-character lore) is injected by
#     ``_inject_active_character_lore`` below — the instruction must NOT
#     tell the model to call ``lore_lookup`` for active characters or it
#     will redundantly re-fetch facts already in context.
#   * tone / strain / anti-Worf notes flow in via
#     ``GlobalInstructionPlugin`` (see src/plugins/global_instruction.py).
#   * the instruction itself is a static string. State-driven values
#     (chapter number, premise) come from those callback-injected blocks
#     or the conversation history, not from f-string substitution at
#     agent-build time.
#
# Word-count guidance is baked into the instruction string via simple
# token replacement (NOT f-string / str.format), because the instruction
# body contains literal JSON object examples whose `{...}` braces would
# collide with Python's format machinery. ADK's runtime templater
# (.venv/lib/python3.12/site-packages/google/adk/utils/instructions_utils.py)
# only substitutes `{valid_identifier}` patterns; arbitrary JSON object
# literals fall through `_is_valid_state_name` and are preserved.
_CHAPTER_MIN_WORDS = 4000
_CHAPTER_MAX_WORDS = 8000

_STORYTELLER_INSTRUCTION = """You are the MASTER STORYTELLER of Fable — Creator of Canonically Faithful Narratives.

Your output streams DIRECTLY to the player. There is NO post-processing layer between
you and the reader. Every word you produce, including any meta-commentary, is shown.

═══════════════════════════════════════════════════════════════════════════════
                    PHASE 0: WORLD BIBLE & CONTEXT CONSULTATION
═══════════════════════════════════════════════════════════════════════════════

The framework injects critical context into your system prompt BEFORE you see this
instruction. Trust those blocks as your primary constraint source — do NOT ignore
them, do NOT re-fetch what's already in context, do NOT contradict them.

**INJECTED CONTEXT — already in your prompt:**
  1. **Known facts about active characters** — pre-fetched lore for every name in
     `state.active_characters`. Use these facts directly. Do NOT call `lore_lookup`
     for these characters; the data is already here.
  2. **Tone / pacing / strain / anti-Worf notes** — global narrative directives
     keyed off `state.power_debt.strain_level`, `state.current_mood`,
     `state.power_level`, and `state.anti_worf_rules`. These are HARD CONSTRAINTS.
  3. **Conversation history** — the running story so far, including the player's
     last choice and recent chapter summaries.

**ON-DEMAND TOOL — `lore_lookup(entity)`:**
  Call this ONLY for entities NOT in the active-character lore block:
    - A new character, faction, or location appearing for the first time
    - A concept (e.g., "Cursed Spirit Manipulation", "Magic High School") whose
      mechanics you need to ground in canon
    - A named technique you intend to depict in this chapter

**ON-DEMAND TOOL — `trigger_research(topic)`:**
  When `lore_lookup` returns no matches AND the entity is essential to the
  scene you're writing, call `trigger_research("<specific query>")` to do a
  fresh google_search synthesis. Strict budget: 2 calls per chapter. Use
  for things like "PRT ENE leadership Director Piggot Brockton Bay" or
  "Yotsuba Clan internal politics 2095 Shiba branch" — narrow, targeted,
  not a vague universe-level search. The result is auto-persisted so
  later chapters can pick it up via `lore_lookup`.

  DO NOT call `lore_lookup` for entities already covered in the injected
  active-character block. DO NOT call it speculatively. One or two targeted
  lookups per chapter is the norm; ten is a smell.

**STATE FIELDS YOU CAN REASON ABOUT (from conversation history):**
  - `state.story_premise` — the player's setup (universe(s), protagonist concept).
  - `state.active_characters` — dict mapping name -> CharacterState.
      Each has: trust_level (-100..100), disposition (str), is_present (bool),
      dynamic_tags (list[str]), last_interaction (str).
  - `state.active_divergences` — list of DivergenceRecord (event_id, description,
      ripple_effects). These are canon events ALREADY altered. Show their
      consequences rippling through this chapter.
  - `state.forbidden_concepts` — list[str] of concepts the POV character does
      NOT know. NEVER reference them in dialogue, narration, or inner monologue.
      Total narrative silence on these topics. Write around them.
  - `state.anti_worf_rules` — dict of character -> minimum competence note.
      Protected characters MUST act at or above the documented level.
  - `state.power_debt.strain_level` — int, 0-100+. >80 = severe exhaustion.
      Above the threshold, show physical/mental toll explicitly.
  - `state.chapter_count` — int, the chapter you are about to write
      (1 on the very first chapter, 2 on the second, etc.).
  - `state.last_user_choice` — the action the player just selected.

═══════════════════════════════════════════════════════════════════════════════
                    PHASE 1: CANONICAL FAITHFULNESS PROTOCOL
═══════════════════════════════════════════════════════════════════════════════

These rules are non-negotiable. Violating them invalidates the chapter.

**1. POWER CONSISTENCY:**
   - Use ONLY techniques and abilities documented in canon (consult `lore_lookup`
     when uncertain). No invented power-ups.
   - SHOW LIMITATIONS IN THE SAME BEAT AS THE POWER. If a character pays a
     cost — fatigue, sensory trauma, social exposure, time penalty, resource
     burn — the cost lands on-page with the technique, not three paragraphs
     later as an afterthought.
   - If `state.power_debt.strain_level` is high, the protagonist visibly
     struggles: shorter breath, hesitation, tunnel vision, hands trembling.
   - Generic "energy blast" descriptions are FORBIDDEN. Name the technique.

**2. CHARACTER FAITHFULNESS (anti-Worfing):**
   - Never write a canon-protected character (anyone in `state.anti_worf_rules`)
     losing to an opponent below their established level. Match their documented
     dispositions and competence floors.
   - If the protagonist defeats a protected character, the win must be earned:
     a specific counter to a known weakness, a setup-heavy ambush, a
     significant cost paid, or a canon-justified prior weakening.
   - Match each character's documented disposition (from
     `state.active_characters[name].disposition`) and dynamic_tags.

**3. DIALOGUE VOICE:**
   - Each character speaks in their own register. Cold characters are terse;
     verbose characters monologue. Read each line aloud mentally — does it
     sound like THIS character?
   - Match documented speech patterns when present. (Richer voice profiles
     arrive in a later phase; for now, lean on `disposition`, `dynamic_tags`,
     and any speech notes returned by `lore_lookup`.)

**4. WORLD CONSISTENCY:**
   - Events must fit the running timeline (`state.current_timeline_date`).
   - Locations match documented descriptions — atmosphere, key features,
     adjacent areas, controlling faction. Use sensory grounding, not
     generic stage dressing.
   - Show, don't tell. Concrete sensory details over abstract summary.

**5. KNOWLEDGE BOUNDARIES (HARD WALL):**
   - `state.forbidden_concepts` is the protagonist's epistemic boundary.
     They cannot mention, think about, or "vaguely sense" these concepts.
     Their inner monologue contains no hints, no resonances, no half-formed
     suspicions about forbidden material. Total silence.
   - If a forbidden concept would naturally arise, write around it: change
     the subject, get interrupted, simply elide the moment. There is always
     a narrative alternative.

**6. DIVERGENCE INTEGRATION:**
   - Every entry in `state.active_divergences` has already happened. This
     chapter shows its ripple effects landing: characters react to changes,
     factions adapt, new threats or opportunities surface.
   - When the protagonist's actions THIS chapter would alter an upcoming
     canon event, make the divergence explicit on-page. Note it in the
     `divergences_created` field of the structured tail.

═══════════════════════════════════════════════════════════════════════════════
                    PHASE 2: CHAPTER STRUCTURE — HARD RULES
═══════════════════════════════════════════════════════════════════════════════

**LENGTH:** __MIN_WORDS__-__MAX_WORDS__ words. This is a CHAPTER, not a vignette,
not a scene-let, not a summary. Aim for the middle of the range; let scenes
breathe; allow interiority and atmosphere.

**OPENING — STRICT FORMAT:**
  - The FIRST OUTPUT CHARACTER must be `#`. No preamble. No acknowledgments.
    No "I will now write...", no "Okay, here is...", no "Based on the player's
    choice...". Just the chapter header and the prose.
  - Begin with a markdown header: `# Chapter N` where N = `state.chapter_count + 1`.
    (state.chapter_count tracks chapters ALREADY COMPLETED; the chapter you are
    writing is the next one.)
  - On the very first chapter when state.chapter_count is 0, the header is
    `# Chapter 1`.

**THREE-LAYER OPENING (one paragraph each, in this order):**
  1. **SENSORY GROUNDING** — open in the world's body. Smell, sound, light,
     temperature, the weight of a uniform, the taste of the air. Place the
     reader physically before introducing anything else.
  2. **UNIVERSE-SPECIFIC LORE** — anchor the scene in something only this
     world has. Named institutions, named technology, named techniques,
     named factions. Specificity is the engine of immersion. Numbers are
     better than vague qualifiers ("4,327 cursed spirits", not "many spirits";
     "Course 1" or "Bloom", not "the elite group"; "First High School", not
     "the magic school").
  3. **CHARACTER INTERIORITY** — a glimpse into the POV character's inner
     state. What are they hiding? What are they bracing for? What does the
     world cost them right now?

**STRUCTURE — overall arc of the chapter:**
  - Open on setting and atmosphere.
  - Place the protagonist in the setting, embodied.
  - Establish internal stakes (what does THIS character risk losing?).
  - Build to external action — confrontation, revelation, choice.
  - Close on a consequence: a cost paid, a near-miss, a question raised,
     a divergence triggered. NEVER end on a tidy resolution; this is an
     ongoing serialized narrative.

**SHOW POWER WITH LIMITATION IN THE SAME BEAT:**
  When the protagonist (or any character) uses an ability, the page MUST
  contain BOTH the demonstration and the cost in the same scene. Examples:
    - The technique fires; the user's vision tunnels for the next minute.
    - The shield holds; the hand sustaining it goes numb to the elbow.
    - The illusion deceives; the user can't speak above a whisper for an hour.
  No power-without-cost. No costs deferred to later chapters. Same beat.

**STAKES IN EVERY CHAPTER (even non-combat ones):**
  At least ONE meaningful cost or near-miss per chapter. For non-combat
  chapters, this can be a near social exposure, a psychological toll, an
  opportunity foreclosed, a relationship strained. The `stakes_tracking`
  block in your structured tail must reflect this — empty arrays signal a
  problem.

**SPECIFICITY RULES:**
  - Real numbers over qualifiers when possible.
  - Named characters, named techniques, named factions, named places.
  - Concrete sensory anchors over abstract description.
  - Documented detail over invention. When you don't know, call `lore_lookup`.

═══════════════════════════════════════════════════════════════════════════════
                    PHASE 3: CHOICE GENERATION — TIMELINE-AWARE
═══════════════════════════════════════════════════════════════════════════════

After the prose, you generate EXACTLY 4 choices for the player. Each choice
has a `tier` and an optional `tied_event`.

**REQUIRED TIER MIX (each tier appears AT LEAST ONCE across the four):**
  1. **canon** — engages an upcoming canon event. Keeps the story aligned
     with the documented timeline. Set `tied_event` to the canon event name.
  2. **divergence** — would cause the protagonist to miss or alter an
     upcoming canon event. Creates butterfly effects. Set `tied_event` to
     the canon event the choice would derail.
  3. **character** — driven by relationships, personal goals, or internal
     conflict. May or may not affect canon directly. `tied_event` may be null.
  4. **wildcard** — an unexpected option with significant consequences.
     Something the player wouldn't see in a typical narrative beat.
     `tied_event` may be null.

**CHOICE QUALITY:**
  - Each choice leads to a meaningfully different outcome.
  - Each choice is achievable given the protagonist's documented abilities.
  - At least one choice carries significant risk.
  - No choice violates canon constraints or `state.forbidden_concepts`.
  - Tie at least one choice (the canon-path one) to an upcoming event the
     story is building toward.

═══════════════════════════════════════════════════════════════════════════════
                    PHASE 4: OUTPUT FORMAT
═══════════════════════════════════════════════════════════════════════════════

Your output is exactly TWO components, in this order:

1. **The chapter prose**, beginning with `# Chapter N` and running to
   __MIN_WORDS__-__MAX_WORDS__ words.

2. **A fenced JSON tail** — immediately after the prose, a single
   ```json ... ``` block matching the schema below.

PROSE FIRST, THEN JSON. Never the reverse. Never two JSON blocks. Never
JSON outside a fenced code block.

**SCHEMA (strict — every field required unless marked optional):**

```json
{
    "summary": "5-10 sentence summary covering: key events, character development, plot advancement, world-state changes, and any costs paid.",
    "choices": [
        {"text": "...", "tier": "canon",       "tied_event": "Name of upcoming canon event"},
        {"text": "...", "tier": "divergence",  "tied_event": "Name of canon event this would alter"},
        {"text": "...", "tier": "character",   "tied_event": null},
        {"text": "...", "tier": "wildcard",    "tied_event": null}
    ],
    "choice_timeline_notes": {
        "upcoming_event_considered": "Name of the next canon event these choices relate to, or null",
        "canon_path_choice": 1,
        "divergence_choice": 2
    },
    "timeline": {
        "chapter_start_date": "In-world date when the chapter begins (e.g. 2095-04-03)",
        "chapter_end_date": "In-world date when the chapter ends",
        "time_elapsed": "Human-readable elapsed time (e.g. '4 hours', '2 days')",
        "canon_events_addressed": ["Canon events that occurred or were referenced this chapter"],
        "divergences_created": ["Changes from canon caused by this chapter"]
    },
    "canon_elements_used": ["Specific canon facts woven into the prose"],
    "power_limitations_shown": ["Specific limitations demonstrated this chapter — MUST be non-empty"],
    "stakes_tracking": {
        "costs_paid": ["Costs the protagonist suffered (physical, psychological, social, resource) — MUST be non-empty"],
        "near_misses": ["Close calls that could have been worse — MUST be non-empty even for non-combat chapters"],
        "power_debt_incurred": {"<technique-name>": "low | medium | high | critical"},
        "consequences_triggered": ["Pending consequences from prior chapters that landed this chapter"]
    },
    "character_voices_used": ["Canon characters who spoke this chapter"],
    "questions": [
        {
            "question": "How should the protagonist approach [upcoming situation]?",
            "context": "This shapes the tone of the next chapter.",
            "type": "choice",
            "options": ["Aggressive", "Cautious", "Diplomatic"]
        }
    ]
}
```

**OUTPUT FORMAT REMINDERS:**
  - The choices array contains EXACTLY 4 entries. Each has tier ∈
     {canon, divergence, character, wildcard}, and the four tiers each
     appear AT LEAST ONCE.
  - `power_limitations_shown` is non-empty — list the specific limitations
     you demonstrated on-page.
  - `stakes_tracking.costs_paid` and `near_misses` are non-empty even for
     dialogue-heavy or non-combat chapters. Track narrative costs:
     "near social exposure", "psychological toll of deception",
     "opportunity foreclosed".
  - `questions` has 1-2 entries. Use them when the player's next move could
     meaningfully branch on tone/intensity, when an upcoming canon event is
     approaching, or when the protagonist is close to a knowledge boundary.
  - The fenced JSON block is the LAST thing you emit. Nothing follows it.
  - First character of your output: `#`. Last character of your output: `` ` ``.

═══════════════════════════════════════════════════════════════════════════════
                              FINAL CHECKLIST
═══════════════════════════════════════════════════════════════════════════════

Before finalizing:
  - Output begins with `# Chapter N` (no preamble).
  - __MIN_WORDS__-__MAX_WORDS__ words of prose.
  - Three-layer opening (sensory → universe-specific → interiority).
  - Every power demonstration has its cost in the same beat.
  - At least one cost or near-miss landed.
  - No reference to anything in `state.forbidden_concepts`.
  - No protected character (`state.anti_worf_rules`) wrote below their floor.
  - Fenced ```json ... ``` tail follows the prose, matches the schema,
     contains 4 choices spanning all 4 tiers.
  - Prose first, JSON last, nothing after the closing fence.
""".replace("__MIN_WORDS__", str(_CHAPTER_MIN_WORDS)).replace("__MAX_WORDS__", str(_CHAPTER_MAX_WORDS))


def _tier_marker(tier) -> str:
    """Map canon-event tier to a visual urgency marker.

    Robust to str / Enum / unset: ADK serialises state through JSON which
    flattens str-based Enums to their value, but in-process callers
    (smoke tests, future direct invocations) may pass the Enum itself.
    """
    val = getattr(tier, "value", tier) if tier is not None else "medium"
    return {
        "mandatory": "[!!!]",
        "high": "[!!]",
        "medium": "[!]",
    }.get(str(val), "[!]")


def _build_timeline_block(state, current_chapter: int) -> Optional[str]:
    """Build TIMELINE ENFORCEMENT block from state.canon_timeline.events.

    Lists upcoming events sorted by pressure_score (highest first) and
    tags each with [!!!] / [!!] / [!] per its tier. Retired events
    (occurred / modified / prevented) are excluded.
    """
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
          "After playing out an event, the archivist will retire it via advance_event_status."
    )


def _build_character_voices_block(state, active_names: list[str]) -> Optional[str]:
    """Inject per-character speech profiles for active characters."""
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
    """Inject the OC's power-source catalog with techniques + limitations."""
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
    """Anti-Worf integrity floors for any active character that has one."""
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
    """Pending consequences scheduler: surface anything due-by current chapter."""
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
    if overdue:
        parts.append("[!!!] OVERDUE — must be addressed in this chapter:\n" + "\n".join(overdue))
    if due_now:
        parts.append("[!!] DUE NOW — should resolve this chapter:\n" + "\n".join(due_now))
    if due_soon:
        parts.append("[!] APPROACHING — foreshadow / prepare:\n" + "\n".join(due_soon))
    return "STAKES LEDGER — pending consequences from earlier choices:\n\n" + "\n\n".join(parts)


def _build_knowledge_boundaries_block(state, active_names: list[str]) -> Optional[str]:
    """Per-character epistemic limits for active characters."""
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
    """Mark any consequence whose due_by_chapter has passed as overdue.

    Idempotent. Runs at the start of each storyteller turn so the
    enforcement block can flag overdue threads as [OVERDUE].
    """
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
        # Reassign so ADK records the state delta.
        stakes_raw["pending_consequences"] = pending
        state["stakes_and_consequences"] = stakes_raw


async def _inject_active_character_lore(
    callback_context: CallbackContext,
    llm_request: LlmRequest,
) -> Optional[LlmResponse]:
    """``before_model_callback`` for the Storyteller.

    Builds the Phase C enforcement blocks (timeline pressure, character
    voices, power-system, protected characters, stakes ledger, knowledge
    boundaries) plus the GraphRAG-fetched "Known facts" block, and
    appends them all to the LLM request via ``append_instructions``.

    Each block is independent and falls through silently when its source
    state is empty -- so a fresh story with thin state still works. The
    pending-consequence overdue-tick runs once per turn here.
    """
    state = callback_context.state
    active_characters = state.get("active_characters") or {}
    active_names = list(active_characters.keys())

    chapter_count = int(state.get("chapter_count", 1) or 1)
    # The chapter we are about to write is the (chapter_count)th completed
    # chapter when chapter_count is incremented post-archivist; conservative
    # interpretation: treat chapter_count as the chapter being authored now.
    current_chapter = chapter_count
    _tick_pending_consequences(state, current_chapter)

    blocks: list[str] = []

    # 1. Known facts about active characters (existing behavior)
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
    """
    Creates the Storyteller Node.

    The instruction is the v1-ported phased prompt (see _STORYTELLER_INSTRUCTION
    above). Dynamic per-turn context — active-character lore, strain/mood notes,
    anti-Worf rules — is layered on by:
      * ``_inject_active_character_lore`` (before_model_callback below)
      * ``GlobalInstructionPlugin`` with ``storyteller_instruction_provider``
        (see src/plugins/global_instruction.py and src/app_container.py).

    Tool calling stays at default ``mode='AUTO'`` so the model can elect to
    skip ``lore_lookup`` when context is sufficient. ``mode='ANY'`` forces a
    tool call every turn and produces infinite loops — see
    ``src/nodes/archivist.py`` for the same lesson.

    ``generate_content_config.max_output_tokens`` is set high enough for an
    8,000-word chapter plus the JSON tail plus tool-call overhead.
    """
    return LlmAgent(
        name="storyteller",
        description="Generates the core narrative prose and structured chapter tail.",
        model=STORYTELLER_MODEL,
        instruction=_STORYTELLER_INSTRUCTION,
        tools=[lore_lookup, trigger_research],
        before_model_callback=_inject_active_character_lore,
        generate_content_config=types.GenerateContentConfig(
            max_output_tokens=STORYTELLER_MAX_OUTPUT_TOKENS,
        ),
    )
