from __future__ import annotations

import logging
import re
from typing import Optional

from google.adk.agents.callback_context import CallbackContext
from google.adk.agents.llm_agent import LlmAgent
from google.adk.models.llm_request import LlmRequest
from google.adk.models.llm_response import LlmResponse
from google.genai import types

from src.state.storyteller_output import StorytellerOutput
from src.tools.lore_lookup_tool import lore_lookup, retrieve_lore
from src.tools.research_tools import trigger_research
from src.utils.canon_arcs import lookup_arc

# Storyteller uses the larger gemini-3-flash-preview to honor the 4-8k word
# chapter target. The lite tier ('gemini-3.1-flash-lite') compresses
# responses to ~1-2k words regardless of prompt instructions.
STORYTELLER_MODEL = "gemini-3-flash-preview"

# Token budget for a structured output containing 4-8k words of prose plus the
# chapter_meta tail plus tool-call overhead.
STORYTELLER_MAX_OUTPUT_TOKENS = 24576

logger = logging.getLogger("fable.storyteller")

_CHAPTER_MIN_WORDS = 4000
_CHAPTER_MAX_WORDS = 8000

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
                    PROMPT STRUCTURE — READ THIS FIRST
══════════════════════════════════════════════════════════════════════════════════════

Your prompt is composed of CONSTRAINT BLOCKS appended below this base
instruction. They are ordered by priority and tagged with markers:

  [!!!] INVIOLABLE — violation = chapter rejected by audit.
  [!!]  STRONG    — violation = audit warning + likely retry.
  [!]   GUIDANCE  — preferred but flexible.

When constraints conflict, the higher-priority marker wins. Block order:

  1. OPERATIONAL CONTRACT     — output schema + word target + priority rules.
  2. STORY UNIVERSE           — universes, tone, mood, in-world date, scale.
  3. PROTAGONIST FRAMEWORK    — [!!!] OC premise + setup-wizard answers.
  4. PLAYER DIRECTIVE         — [!!!] the chapter's PRIMARY ACTION.
  5. ARC CONTEXT              — [!!] canonical world-state + knowledge horizons.
  6. CURRENT SCENE STATE      — OC's location, strain, recent feats.
  7. NARRATIVE LEDGER         — [!!] divergences, consequences, threads.
  8. CHAPTER CONTINUITY       — chapter summaries + closing-prose tail.
  9. CHARACTER VOICES         — match the patterns when these chars speak.
 10. CAST DOSSIER             — [!!] canonical retrieval per active character.
 11. TIMELINE ENFORCEMENT     — upcoming canon events; tier-marked.
 12. POWER SYSTEM             — OC's powers; cost+limit MUST appear in-beat.
 13. PROTECTED CHARACTERS     — [!!] competence floors / anti-Worf rules.
 14. KNOWLEDGE BOUNDARIES     — [!!!] forbidden concepts / per-char limits.
 15. STYLE ANCHOR             — canonical prose register samples (when present).
 16. ANTI-PATTERN              — [!!] failure modes + recent openings to AVOID.
 17. AUDIT FEEDBACK           — recent violations to self-correct from.
 18. CHAPTER OUTPUT REMINDER  — final reminder of the output contract.

Trust those blocks as authoritative. Do NOT ignore them. Do NOT re-fetch
information already in context. Use the on-demand tools below sparingly
to fill genuine gaps.

══════════════════════════════════════════════════════════════════════════════════════
                    ON-DEMAND TOOLS — sparing use
══════════════════════════════════════════════════════════════════════════════════════

`lore_lookup(entity)` — pull canonical chunks for a character / faction /
location / event NOT covered in CAST DOSSIER. Also recalls older chapters
via `lore_lookup("chapter N")`. Two or three targeted lookups per
chapter is the norm; do NOT call for entities already in CAST DOSSIER.

`trigger_research(topic)` — strict budget of 2 calls per chapter. Use
only when `lore_lookup` returns nothing AND the entity is essential.
Narrow, targeted queries.

══════════════════════════════════════════════════════════════════════════════════════
                    CANONICAL FAITHFULNESS PROTOCOL
══════════════════════════════════════════════════════════════════════════════════════

**1. POWER CONSISTENCY:** Use ONLY canonically-documented techniques.
   Generic "energy blast" is FORBIDDEN; name the technique. The POWER
   SYSTEM block lists every cost and limitation. Show limitations when
   they're narratively meaningful — at the edge of a technique's range,
   when an opponent counters, at a stakes moment — NOT as a per-action
   tax. A canon-skilled OC uses powers competently the majority of the
   time; on-page cost is reserved for character/tension/stakes beats.
   Strain bands (see CURRENT SCENE STATE):
     <50  → functions normally; do not manufacture fatigue.
     50-80 → light wear surfacing only when the scene is about exertion.
     >80  → chapter-defining fatigue beat earned (reserved for actual
            punishing feats, not filler tax).

**2. ANTI-WORF / PROTECTED CHARACTERS:** Never write a protected
   character losing to an opponent below their established level. If
   the OC defeats one, the win must be earned via specific counter /
   setup / cost / canon-justified weakening. See PROTECTED CHARACTERS.

**3. DIALOGUE VOICE:** Each character speaks in their own register.
   Match documented patterns from the CHARACTER VOICES block.

**4. KNOWLEDGE WALL (INVIOLABLE):** Items in KNOWLEDGE BOUNDARIES are
   epistemic walls. The OC cannot mention, think about, or "vaguely
   sense" forbidden concepts. Total silence. Write around them: change
   the subject, get interrupted, elide the moment. Per-character
   knowledge limits apply equally — never write a character referencing
   what they canonically don't know.

**5. DIVERGENCE INTEGRATION:** Active divergences (NARRATIVE LEDGER)
   have already happened. This chapter SHOWS their ripples landing.

**6. PLAYER DIRECTIVE WINS CONFLICTS:** When the player directive sends
   the OC somewhere or asks for a particular focus, that overrides
   continuity tension. Do NOT pad with returning-to-prior-location
   prose if the directive sends the OC elsewhere. ≥60% of the chapter's
   prose must enact the directive. See ANTI-PATTERN.

══════════════════════════════════════════════════════════════════════════════════════
                    CHAPTER STRUCTURE — HARD RULES
══════════════════════════════════════════════════════════════════════════════════════

**LENGTH:** __MIN_WORDS__-__MAX_WORDS__ words of prose. Aim for the middle
of the range. Let scenes breathe; allow interiority woven into action.

**PROSE FIELD — NO MARKDOWN HEADER:** The `prose` field contains the
chapter body ONLY. Do NOT include `# Chapter N`. The framework prepends.

**OPENING:** Open with ACTION, DIALOGUE, or a DIRECT CONTINUATION beat
that enacts the player directive immediately. Sensory grounding and
universe-specific lore are woven INTO the opening (smell of ozone as
the OC moves, the named institution mentioned mid-thought) — they are
NOT a standalone first paragraph of weather/atmosphere. The ANTI-PATTERN
block lists recent openings to AVOID; do not start the chapter
similarly.

**STRUCTURE:** Enact the player directive → land the consequences of
prior choices (NARRATIVE LEDGER) → escalate via specific canon
constraints → close on a consequence (cost paid, near-miss, question
raised, divergence triggered). Never end on tidy resolution. Do NOT
cliffhanger on the verge of the directive's primary action — show it
carried out, with consequences.

**STAKES IN EVERY CHAPTER (even non-combat):** At least ONE meaningful
cost or near-miss. For dialogue-heavy chapters: near-exposure,
psychological toll, opportunity foreclosed, relationship strained.

**SPECIFICITY:** Real numbers, named characters/techniques/factions/
places, concrete sensory anchors, documented detail. Specificity is the
engine of immersion. Numbers > vague qualifiers.

══════════════════════════════════════════════════════════════════════════════════════
                    CHOICE GENERATION — TIMELINE-AWARE
══════════════════════════════════════════════════════════════════════════════════════

Generate EXACTLY 4 choices in `chapter_meta.choices`. Each has `tier` and
optional `tied_event`. REQUIRED TIER MIX (each appears exactly once):

  1. **canon**       — engages an upcoming canon event. `tied_event` = the event name.
  2. **divergence**  — would alter or skip an upcoming canon event.
  3. **character**   — driven by relationships, personal goals, interior conflict.
  4. **wildcard**    — unexpected option with significant consequences.

Each choice leads to a meaningfully different outcome. Each is
achievable. At least one carries significant risk. None violate canon
constraints or `forbidden_concepts`.

Generate 1-2 `chapter_meta.questions` for tone/style branching: when an
upcoming canon event is approaching, near a knowledge boundary, or when
the next chapter could branch on intensity.

══════════════════════════════════════════════════════════════════════════════════════
                    STRUCTURED OUTPUT (StorytellerOutput)
══════════════════════════════════════════════════════════════════════════════════════

Single output: `StorytellerOutput` with two top-level fields:

  - `prose` (str): __MIN_WORDS__-__MAX_WORDS__ words. NO markdown header.

  - `chapter_meta` (ChapterOutput): the structured tail. Required:
    summary (5-10 sentences); choices (4 entries, all 4 tiers);
    choice_timeline_notes; timeline (chapter_start/end_date,
    time_elapsed, canon_events_addressed, divergences_created);
    canon_elements_used; power_limitations_shown (MUST be non-empty
    when powers used); stakes_tracking (costs_paid + near_misses MUST
    be non-empty); character_voices_used; questions (1-2).

══════════════════════════════════════════════════════════════════════════════════════
                              FINAL CHECKLIST
══════════════════════════════════════════════════════════════════════════════════════

Before emitting:
  - PLAYER DIRECTIVE enacted, with ≥60% of prose in the directive's setting.
  - Did NOT open with weather/atmosphere or repeat a recent opening.
  - prose has __MIN_WORDS__-__MAX_WORDS__ words; NO `# Chapter N` header.
  - Every power demo has its cost shown in the same beat.
  - At least one cost or near-miss landed.
  - No reference to anything in KNOWLEDGE BOUNDARIES (meta or per-character).
  - No protected character wrote below their floor.
  - Active divergences from NARRATIVE LEDGER have ripples shown landing.
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


_YEAR_RE = re.compile(r"\b(\d{4})\b")


def _extract_year(date_str) -> Optional[int]:
    """Pull the first 4-digit year from a free-form in-world date string.

    Handles every shape we've seen in practice:
      - "April 2095"
      - "October 2018 (Contextual)"
      - "2095-04-18 Evening"
    Returns None when no year is present.
    """
    if not date_str:
        return None
    m = _YEAR_RE.search(str(date_str))
    return int(m.group(1)) if m else None


# Events whose in-world date is more than this many years from the story's
# current_timeline_date are demoted from MANDATORY/HIGH/MEDIUM markers to
# a "[context]" backstory framing. Without this filter, a story set in
# 2095 (Mahouka) had JJK 2017-2018 events flagged MANDATORY -- the model
# was being told 77-year-old historical events were required chapter beats.
_TIMELINE_PROXIMITY_YEARS = 5


def _build_timeline_block(state, current_chapter: int) -> Optional[str]:
    """Build TIMELINE ENFORCEMENT block from state.canon_timeline.events.

    Events get a priority marker derived from their `tier` field. Events
    whose `in_world_date` is far from the story's `current_timeline_date`
    (more than _TIMELINE_PROXIMITY_YEARS in either direction) are re-tagged
    `[context]` regardless of tier -- they're backstory the world is built
    on, not chapter beats to advance.
    """
    timeline = state.get("canon_timeline") or {}
    events = timeline.get("events") if isinstance(timeline, dict) else None
    if not events:
        return None

    upcoming = [e for e in events if isinstance(e, dict) and e.get("status", "upcoming") == "upcoming"]
    if not upcoming:
        return None
    upcoming.sort(key=lambda e: int(e.get("pressure_score", 0)), reverse=True)

    # Anchor: the story's current in-world year. Falls back to the premise
    # text if current_timeline_date is unset (early chapters before any
    # time advance has been recorded).
    current_year = (
        _extract_year(state.get("current_timeline_date"))
        or _extract_year(state.get("story_premise") or "")
    )

    has_context_demotion = False
    lines = []
    for ev in upcoming[:12]:
        ev_date = ev.get("in_world_date") or ""
        ev_year = _extract_year(ev_date)
        # Demotion conditions:
        #   1. Far in time: known year > 5 years away from current.
        #   2. Unparseable date: events with no extractable year (e.g.
        #      "Unknown (End of Worm Cycle)") cannot be safely placed
        #      relative to the story's "now" -- demote to [context] so
        #      they aren't flagged MANDATORY at every chapter.
        if current_year is None or ev_year is None:
            is_far_in_time = ev_year is None  # always demote unparseable dates
        else:
            is_far_in_time = abs(current_year - ev_year) > _TIMELINE_PROXIMITY_YEARS
        if is_far_in_time:
            marker = "[context]"
            has_context_demotion = True
        else:
            marker = _tier_marker(ev.get("tier", "medium"))
        name = ev.get("name", "(unnamed event)")
        date = ev.get("in_world_date", "")
        date_part = f" — {date}" if date else ""
        lines.append(f"{marker} **{name}**{date_part}")
        playbook = ev.get("playbook") or ""
        if playbook:
            lines.append(f"  · {playbook}")

    rules = (
        "Rules: [!!!] MANDATORY events MUST appear in this chapter. "
        "[!!] HIGH events should be foreshadowed or prepared. "
        "[!] MEDIUM events may be woven in when narratively appropriate. "
        "After playing out an event, the archivist will retire it via "
        "canon_event_status_updates."
    )
    if has_context_demotion:
        rules += (
            " [context] events are historical backstory (>5 years from "
            "the current in-world date); reference for tone or causation "
            "but do NOT treat as a chapter beat."
        )

    return (
        "TIMELINE ENFORCEMENT — upcoming canon events the chapter must engage with:\n\n"
        + "\n".join(lines)
        + "\n\n"
        + rules
    )


def _build_character_voices_block(state, active_names: list[str]) -> Optional[str]:
    """Build the CHARACTER VOICES block.

    For active characters with a voice profile in state.character_voices,
    render the canonical voice constraints. For active characters WITHOUT
    a voice profile, emit an explicit placeholder telling the model to
    defer to canon characterisation -- without this placeholder, the
    character was silently omitted and the model wrote their dialogue
    freestyle from training data with no canonical anchor.
    """
    voices = state.get("character_voices") or {}
    if not active_names:
        return None
    blocks = []
    for name in active_names:
        v = voices.get(name)
        if not v:
            blocks.append(
                f"**{name}**\n"
                f"  - (voice profile not yet seeded — defer to your canonical "
                f"knowledge of this character; the archivist will capture "
                f"their voice profile after they speak in this chapter)"
            )
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
    """PROTECTED CHARACTERS — surfaces canon_character_integrity rules.

    Shows BOTH:
      - Active characters with integrity entries (rich format with rules)
      - Non-active canon_character_integrity entries (compact format) so
        the OC could encounter them off-stage / in cameos / in mentions
        without the model writing them off-canon.
    Plus state.anti_worf_rules entries that aren't in canon_character_integrity.
    """
    integrity = state.get("canon_character_integrity") or {}
    anti_worf = state.get("anti_worf_rules") or {}
    if not integrity and not anti_worf:
        return None
    active_set = set(active_names)
    rich_blocks: list[str] = []
    cameo_blocks: list[str] = []
    for name, rec in integrity.items():
        if not isinstance(rec, dict):
            continue
        lines = [f"**{name}**"]
        if rec.get("minimum_competence"):
            lines.append(f"  - ALWAYS can: {rec['minimum_competence']}")
        if rec.get("anti_worf_notes"):
            lines.append(f"  - notes: {rec['anti_worf_notes']}")
        if name in active_set:
            rich_blocks.append("\n".join(lines))
        else:
            cameo_blocks.append("\n".join(lines))
    # anti_worf_rules entries that aren't already covered by integrity
    for name, rule in anti_worf.items():
        if name in integrity:
            continue
        block = f"**{name}**\n  - rule: {rule}"
        if name in active_set:
            rich_blocks.append(block)
        else:
            cameo_blocks.append(block)
    if not rich_blocks and not cameo_blocks:
        return None
    parts = ["[!!] PROTECTED CHARACTERS — competence floors. NEVER write these characters\nlosing to opponents below their level; OC victories must be earned via concrete\nsetup, weakness exploitation, or significant cost."]
    if rich_blocks:
        parts.append("\n─── Active in this chapter ───\n\n" + "\n\n".join(rich_blocks))
    if cameo_blocks:
        parts.append("\n─── Reference (off-stage / cameo / mention) ───\n\n" + "\n\n".join(cameo_blocks))
    return "\n".join(parts)


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


# ════════════════════════════════════════════════════════════════════════════
# NEW PROMPT BLOCK BUILDERS — Phase H redesign
# Each returns Optional[str]; falls through silently when source state empty.
# ════════════════════════════════════════════════════════════════════════════


def _build_operational_contract_block(current_chapter: int) -> str:
    """Top-of-prompt rules. Output schema, word target, do-not-narrate-this rules."""
    return (
        f"OPERATIONAL CONTRACT — Chapter {current_chapter}\n"
        f"\n"
        f"You are the storyteller. Your output is a StorytellerOutput Pydantic\n"
        f"object containing prose + chapter_meta. Word target: {_CHAPTER_MIN_WORDS}-{_CHAPTER_MAX_WORDS}\n"
        f"words of prose. Do NOT include a `# Chapter N` markdown header in prose --\n"
        f"the framework prepends it deterministically.\n"
        f"\n"
        f"Below this contract are CONSTRAINT BLOCKS. They are categorised by\n"
        f"priority marker:\n"
        f"  [!!!] INVIOLABLE — violation = chapter rejected.\n"
        f"  [!!]  STRONG    — violation = audit warning + likely retry.\n"
        f"  [!]   GUIDANCE  — preferred but flexible.\n"
        f"\n"
        f"When constraints conflict, the higher-priority marker wins.\n"
        f"The PLAYER DIRECTIVE block (immediately below the framework) is\n"
        f"[!!!] INVIOLABLE — it is the primary action of THIS chapter.\n"
    )


def _build_story_universe_block(state) -> Optional[str]:
    """STORY UNIVERSE — universes, tone, mood, date, power level. Sets the
    overall stage so the model knows what kind of story it's writing."""
    universes = state.get("universes") or []
    tone = (state.get("story_tone") or "").strip()
    mood = (state.get("current_mood") or "").strip()
    date = (state.get("current_timeline_date") or "").strip()
    power_level = (state.get("power_level") or "").strip()
    location = (state.get("current_location_node") or "").strip()
    if not (universes or tone or mood or date or power_level):
        return None
    lines = ["STORY UNIVERSE & STAGE"]
    if universes:
        lines.append(f"  Universes: {' × '.join(universes)} (crossover)")
    if date:
        lines.append(f"  In-world date: {date}")
    if location and location != "Unknown":
        lines.append(f"  Current location: {location}")
    if tone:
        lines.append(f"  Story tone: {tone} — keep this register throughout.")
    if mood:
        lines.append(f"  Current chapter mood: {mood}")
    if power_level:
        lines.append(f"  Power scale: {power_level}-tier conflict.")
    return "\n".join(lines)


def _build_player_directive_block(state) -> Optional[str]:
    """[!!!] PLAYER DIRECTIVE — the most important block. Promoted from
    the buried tail of PRIOR CHAPTER CONTEXT to its own top-level slot."""
    last_user_choice = (state.get("last_user_choice") or "").strip()
    last_user_q_answers = state.get("last_user_question_answers") or {}
    if not last_user_choice and not last_user_q_answers:
        return None
    lines = [
        "[!!!] PLAYER DIRECTIVE — INVIOLABLE PRIMARY ACTION FOR THIS CHAPTER",
        "",
        "This is what the player explicitly told the OC to do. It overrides",
        "any continuity tension. It is the chapter's PRIMARY ACTION.",
        "",
        "Rules of engagement with this directive:",
        "  - The chapter MUST enact this directive within the opening 30%",
        "    of prose. NO atmospheric Winslow / school / 'returning home'",
        "    scene-setting if the directive sends the OC elsewhere.",
        "  - At least 60% of the chapter's prose must take place in the",
        "    location / situation the directive implies.",
        "  - If the prior chapter's closing prose conflicts with the",
        "    directive, the DIRECTIVE wins. Resume from where the OC was",
        "    AT THE END of the prior chapter, then immediately enact the",
        "    directive.",
        "  - Do NOT cliffhanger on the verge of the directive. Show the",
        "    directive being CARRIED OUT, not just approached.",
        "",
    ]
    if last_user_choice:
        lines.append("─── Directive (player's selected action + free-text framing) ───")
        lines.append(last_user_choice)
        lines.append("")
    if last_user_q_answers:
        lines.append("─── Tone / style preferences set by the player ───")
        for q, a in last_user_q_answers.items():
            lines.append(f"  • {str(q)[:200]} → {str(a)[:200]}")
    return "\n".join(lines)


def _build_arc_context_block(state) -> Optional[str]:
    """ARC CONTEXT — what's canonically happening at this in-world date in
    each seeded universe. Blocks the model from drifting off-canon by
    explicitly listing what events the world is "supposed to" be living
    through, plus what the OC plausibly knows vs is canon-blind to.
    """
    universes = state.get("universes") or []
    date = (state.get("current_timeline_date") or "").strip()
    if not universes or not date:
        return None
    arc_blocks: list[str] = []
    for univ in universes:
        arc = lookup_arc(univ, date)
        if not arc:
            continue
        block_lines = [f"### {univ} — {arc['name']}"]
        if arc.get("canon_events"):
            block_lines.append("\nCanonical events unfolding in this window:")
            for ev in arc["canon_events"]:
                block_lines.append(f"  - {ev}")
        if arc.get("public_knowledge"):
            block_lines.append("\nWhat the OC plausibly knows (public information):")
            for k in arc["public_knowledge"]:
                block_lines.append(f"  + {k}")
        if arc.get("hidden_knowledge"):
            block_lines.append("\nWhat the OC does NOT know (canon-blind at this date):")
            for k in arc["hidden_knowledge"]:
                block_lines.append(f"  ✗ {k}")
        arc_blocks.append("\n".join(block_lines))
    if not arc_blocks:
        return None
    return (
        "[!!] ARC CONTEXT — the canonical world-state at the current in-world\n"
        "date. Treat the listed events as background reality the OC is moving\n"
        "through. Respect the knowledge horizons strictly: the OC cannot know\n"
        "or 'sense' anything in the canon-blind list, even via subtle hints.\n\n"
        + "\n\n".join(arc_blocks)
    )


def _build_current_scene_state_block(state) -> Optional[str]:
    """CURRENT SCENE STATE — explicit snapshot of where the OC is, what
    they want, and how they're feeling RIGHT NOW. Removes the model's
    need to infer scene context from the prose tail."""
    location = (state.get("current_location_node") or "").strip()
    date = (state.get("current_timeline_date") or "").strip()
    pd = state.get("power_debt") or {}
    strain = int(pd.get("strain_level", 0) or 0)
    recent_feats = pd.get("recent_feats") or []
    mood = (state.get("current_mood") or "").strip()
    if not (location or strain or recent_feats):
        return None
    lines = ["CURRENT SCENE STATE — snapshot of the OC at chapter start"]
    if location and location != "Unknown":
        lines.append(f"  Location: {location}")
    if date:
        lines.append(f"  Time: {date}")
    if mood:
        lines.append(f"  Atmosphere: {mood}")
    if strain:
        if strain < 20:
            band = "fresh, ready"
        elif strain < 50:
            band = "light wear; functions normally"
        elif strain < 80:
            band = "noticeable fatigue when scene focuses on exertion"
        else:
            band = "severe exhaustion — chapter-defining fatigue beat earned"
        lines.append(f"  Strain: {strain}/100 ({band})")
    if recent_feats:
        feats_str = "; ".join(str(f) for f in recent_feats[-5:])
        lines.append(f"  Recent feats (last 5): {feats_str}")
    return "\n".join(lines)


def _build_narrative_ledger_block(state, current_chapter: int) -> Optional[str]:
    """NARRATIVE LEDGER — consolidates active_divergences (already-altered
    canon events) + pending_consequences (overdue/due_now/due_soon) + any
    archivist-tracked narrative_threads."""
    sections: list[str] = []

    # Active divergences (altered canon events)
    divs = state.get("active_divergences") or []
    if divs:
        div_lines = ["─── Active divergences (canon already altered; show ripples landing) ───"]
        for d in divs:
            if not isinstance(d, dict):
                continue
            name = d.get("event_id") or "(unnamed)"
            desc = (d.get("description") or "")[:300]
            div_lines.append(f"  • {name}: {desc}")
            for r in (d.get("ripple_effects") or [])[:5]:
                div_lines.append(f"      ↳ ripple: {str(r)[:240]}")
        sections.append("\n".join(div_lines))

    # Pending consequences (use existing logic)
    stakes = state.get("stakes_and_consequences") or {}
    pending = stakes.get("pending_consequences") if isinstance(stakes, dict) else None
    if pending:
        overdue, due_now, due_soon = [], [], []
        for c in pending:
            if not isinstance(c, dict):
                continue
            due = int(c.get("due_by_chapter", 0) or 0)
            line = f"  - {c.get('action','')} → {c.get('predicted_consequence','')} (due_by={due})"
            if due and due < current_chapter:
                overdue.append(line + " [OVERDUE]")
            elif due == current_chapter:
                due_now.append(line + " [DUE NOW]")
            elif due == current_chapter + 1:
                due_soon.append(line + " [DUE NEXT]")
        consequence_parts = []
        if overdue: consequence_parts.append("[!!!] OVERDUE — must be addressed in this chapter:\n" + "\n".join(overdue))
        if due_now: consequence_parts.append("[!!] DUE NOW — should resolve this chapter:\n" + "\n".join(due_now))
        if due_soon: consequence_parts.append("[!] APPROACHING — foreshadow:\n" + "\n".join(due_soon))
        if consequence_parts:
            sections.append("─── Pending consequences (prior choices coming due) ───\n" + "\n\n".join(consequence_parts))

    # Narrative threads (Phase 3 first-class threads, if populated)
    threads = state.get("narrative_threads") or []
    active_threads = [t for t in threads if isinstance(t, dict) and t.get("status") not in {"resolved", "dormant"}]
    if active_threads:
        thread_lines = ["─── Active narrative threads (advance per status) ───"]
        for t in active_threads:
            status = (t.get("status") or "seeded").upper()
            name = t.get("name") or "(unnamed thread)"
            chars = ", ".join(t.get("key_chars") or [])
            chars_str = f" — chars: {chars}" if chars else ""
            thread_lines.append(f"  [{status}] {name}{chars_str}")
            if t.get("notes"):
                thread_lines.append(f"      note: {str(t['notes'])[:200]}")
        sections.append("\n".join(thread_lines))

    if not sections:
        return None
    return (
        "[!!] NARRATIVE LEDGER — already-set narrative threads the chapter\n"
        "must respect or advance. Failing to land an OVERDUE consequence is\n"
        "a strong audit signal.\n\n"
        + "\n\n".join(sections)
    )


def _build_chapter_continuity_block(state) -> Optional[str]:
    """CHAPTER CONTINUITY — chapter summaries window + tighter prose tail.
    Prose tail trimmed from 1500 → 800 chars to reduce its dominance over
    the player directive's attention budget."""
    chapter_summaries = state.get("chapter_summaries") or []
    last_story_text = state.get("last_story_text") or ""
    if not chapter_summaries and not last_story_text:
        return None
    lines = ["CHAPTER CONTINUITY — pick up directly from the prior beat (UNLESS the player directive sends the OC elsewhere)."]
    if chapter_summaries:
        total = len(chapter_summaries)
        window = chapter_summaries[-10:]
        win_start = max(1, total - len(window) + 1)
        if win_start > 1:
            lines.append(f"\n  …{win_start - 1} earlier chapter(s) summarised; lore_lookup('chapter N') to recall.")
        lines.append(f"\n─── Chapter summaries Ch{win_start}..Ch{total} ───")
        for offset, summary in enumerate(window):
            n = win_start + offset
            lines.append(f"  Ch.{n}: {str(summary)[:500]}")
    if last_story_text:
        # Trimmed: 800 chars not 1500. Less content-dominance over player directive.
        tail = last_story_text[-800:] if len(last_story_text) > 800 else last_story_text
        lines.append(f"\n─── Closing prose of the most recent chapter (~800 chars; tonal anchor only) ───")
        if len(last_story_text) > 800:
            lines.append("…[earlier prose elided]")
        lines.append(tail)
    return "\n".join(lines)


def _build_anti_pattern_block(state) -> Optional[str]:
    """ANTI-PATTERN — explicit do-not list + recent chapter openings to avoid
    repeating. Attacks the model's stylistic ruts directly."""
    recent_openings = state.get("recent_chapter_openings") or []
    base_rules = [
        "Open with action, dialogue, or a direct continuation beat — NOT with weather/atmosphere openings ('The air in X...', 'The morning sun...').",
        "Do NOT pad with returning-to-school / returning-to-base scenes when the player directive sends the OC elsewhere.",
        "Do NOT have the OC 'sense' or 'perceive' meta-knowledge they have no canon basis for (no Shard-aware language, no Entity-language, no Gold-Morning-aware language).",
        "Do NOT cliffhanger on the verge of the directive's primary action. Show it carried out, with consequences.",
        "Do NOT repeat phrases or sensory beats from the prior chapter's closing tail.",
        "Avoid telling the reader 'the city' or 'the world' is feeling something — anchor in concrete sensory detail and the OC's specific perception.",
    ]
    lines = ["[!!] ANTI-PATTERN — failure modes to avoid this chapter\n"]
    for r in base_rules:
        lines.append(f"  - {r}")
    if recent_openings:
        lines.append("")
        lines.append("─── Recent chapter openings — DO NOT start similarly ───")
        for i, o in enumerate(recent_openings, 1):
            lines.append(f"  Ch-{i}: {str(o)[:200]}")
    return "\n".join(lines)


def _build_audit_feedback_block(state) -> Optional[str]:
    """AUDIT FEEDBACK — recent violation_log entries so the model can self-
    correct from its own prior mistakes. Ring buffer of last 5."""
    log = state.get("violation_log") or []
    if not log:
        return None
    recent = log[-5:]
    lines = ["AUDIT FEEDBACK — issues flagged in recent chapters; do not repeat:"]
    for v in recent:
        if not isinstance(v, dict):
            continue
        kind = v.get("violation_type") or "issue"
        char = v.get("character") or ""
        concept = v.get("concept") or ""
        quote = (v.get("quote") or "")[:140]
        sev = v.get("severity") or ""
        ctx_bits = " ".join(filter(None, [f"({sev})" if sev else "", char, concept])).strip()
        lines.append(f"  - [{kind}] {ctx_bits}: {quote!r}")
    return "\n".join(lines)


def _build_style_anchor_block(state) -> Optional[str]:
    """STYLE ANCHOR — 1-2 high-density canonical sentences from the dominant
    universe's corpus. Anchors the prose register to the source material's
    actual tone rather than the model's generic narrative voice. Best-effort:
    silent fall-through if the corpus query fails."""
    universes = state.get("universes") or []
    if not universes:
        return None
    # We don't query the DB synchronously here (that would block the
    # before_model callback unnecessarily). Instead we rely on the
    # Cast Dossier's per-character chunks to anchor style. This block
    # is a placeholder for future work: pre-cache style samples per
    # universe at world_builder time and read from state.style_anchor.
    style_anchor = state.get("style_anchor")
    if not isinstance(style_anchor, dict):
        return None
    samples = style_anchor.get("samples") or []
    if not samples:
        return None
    lines = ["STYLE ANCHOR — match the prose register of these canonical samples:"]
    for s in samples[:2]:
        lines.append(f'  "{str(s)[:280]}"')
    return "\n".join(lines)


def _build_chapter_output_reminder_block(current_chapter: int) -> str:
    """Tail block — reminds the model of the output contract one more time
    in case the long context bumped it from active attention."""
    return (
        f"FINAL REMINDER — output StorytellerOutput. Prose: {_CHAPTER_MIN_WORDS}-{_CHAPTER_MAX_WORDS}\n"
        f"words, NO `# Chapter N` header. chapter_meta with 4-tier choices and\n"
        f"1-2 questions. The PLAYER DIRECTIVE [!!!] block above is the chapter's\n"
        f"primary action — enact it. Do NOT defer it to a cliffhanger.\n"
    )


def _build_protagonist_framework_block(state) -> Optional[str]:
    """PROTAGONIST FRAMEWORK — hard creative direction. The OC is the only
    POV. Canon characters orbit them, not the other way around."""
    premise = (state.get("story_premise") or "").strip()
    setup_conv = state.get("setup_conversation") or []
    if not premise:
        return None
    lines = [
        "[!!!] PROTAGONIST FRAMEWORK — this is the ONLY protagonist of the story.",
        "Every chapter is from this character's POV (or about them in third-person limited).",
        "Do NOT write a chapter focused on canon characters; canon characters orbit the OC.",
        "The framework below is HARD CREATIVE DIRECTION, on par with canon:",
        "",
        premise[:7000] + ("\n…[truncated; full premise persisted in state.story_premise]" if len(premise) > 7000 else ""),
    ]
    if isinstance(setup_conv, list) and setup_conv:
        lines.append("")
        lines.append("─── Setup wizard answers (additional creative direction) ───")
        for entry in setup_conv:
            if not isinstance(entry, dict):
                continue
            role = entry.get("role", "?")
            content = str(entry.get("content", ""))[:400]
            lines.append(f"[{role.upper()}] {content}")
    return "\n".join(lines)


async def _inject_active_character_lore(
    callback_context: CallbackContext,
    llm_request: LlmRequest,
) -> Optional[LlmResponse]:
    """``before_model_callback`` for the Storyteller — Phase H redesign.

    Constructs the storyteller's prompt as a hierarchy of clearly-labeled
    blocks ordered by priority, NOT by the order the data sources appear
    in state. Critical fixes vs the previous design:

      - PLAYER DIRECTIVE is its own top-level [!!!] block, positioned
        EARLY in the prompt rather than buried at the end of PRIOR
        CHAPTER CONTEXT. Models attend to early-prompt content more
        reliably; this stops the prior chapter's prose tail from
        drowning out the player's per-chapter intent.

      - ARC CONTEXT block (NEW) injects canonical world-state at the
        story's in-world date for each seeded universe, with explicit
        knowledge-horizon lists (what the OC plausibly knows vs is
        canon-blind to). Stops omniscient-OC drift.

      - ANTI-PATTERN block (NEW) lists explicit failure modes to avoid
        plus the last 3 chapter openings (model is told NOT to repeat
        their style). Attacks the "atmospheric Winslow opening" rut.

      - NARRATIVE LEDGER consolidates active_divergences +
        pending_consequences + narrative_threads into one block so the
        model sees ALL outstanding plot debts in one place.

      - CURRENT SCENE STATE makes location/strain/recent-feats explicit
        instead of forcing the model to infer from prose tail.

      - Closing prose tail trimmed 1500 → 800 chars (less continuity-
        dominance over the directive's attention budget).

      - All blocks are tagged [!!!]/[!!]/[!] priority markers; the
        OPERATIONAL CONTRACT block at the top documents the hierarchy
        so the model knows how to resolve constraint conflicts.

    Each builder falls through silently when source state is empty.
    The pending-consequence overdue-tick runs once per turn here.
    """
    state = callback_context.state
    active_characters = state.get("active_characters") or {}
    active_names = list(active_characters.keys())

    chapter_count = int(state.get("chapter_count", 1) or 1)
    current_chapter = chapter_count
    _tick_pending_consequences(state, current_chapter)

    # Build block list in PRIORITY ORDER (most important first).
    # Each entry: (label, content_or_None). None entries are skipped at
    # render time so the final prompt has no empty headers.
    raw_blocks: list[tuple[str, Optional[str]]] = [
        ("OPERATIONAL CONTRACT",     _build_operational_contract_block(current_chapter)),
        ("STORY UNIVERSE",           _build_story_universe_block(state)),
        ("PROTAGONIST FRAMEWORK",    _build_protagonist_framework_block(state)),
        ("PLAYER DIRECTIVE",         _build_player_directive_block(state)),
        ("ARC CONTEXT",              _build_arc_context_block(state)),
        ("CURRENT SCENE STATE",      _build_current_scene_state_block(state)),
        ("NARRATIVE LEDGER",         _build_narrative_ledger_block(state, current_chapter)),
        ("CHAPTER CONTINUITY",       _build_chapter_continuity_block(state)),
        ("CHARACTER VOICES",         _build_character_voices_block(state, active_names)),
        ("TIMELINE ENFORCEMENT",     _build_timeline_block(state, current_chapter)),
        ("POWER SYSTEM",             _build_power_system_block(state)),
        ("PROTECTED CHARACTERS",     _build_protected_characters_block(state, active_names)),
        ("KNOWLEDGE BOUNDARIES",     _build_knowledge_boundaries_block(state, active_names)),
        ("STYLE ANCHOR",             _build_style_anchor_block(state)),
        ("ANTI-PATTERN",             _build_anti_pattern_block(state)),
        ("AUDIT FEEDBACK",           _build_audit_feedback_block(state)),
        ("CHAPTER OUTPUT REMINDER",  _build_chapter_output_reminder_block(current_chapter)),
    ]

    # Per-active-character canonical chunk retrieval (Cast Dossier — per-arc
    # version is Phase 2; this is the existing per-character lookup).
    cast_dossier_block: Optional[str] = None
    if active_characters:
        char_blocks: list[str] = []
        for name in active_names:
            matches = await retrieve_lore(name)
            if not matches:
                continue
            bullets: list[str] = []
            for m in matches:
                chunk = (m.get("chunk_text") or "").strip()
                vol = m.get("volume") or "?"
                bullets.append(f"  - [{vol}] {chunk}")
            char_blocks.append(f"### {name} — canonical retrieval\n" + "\n".join(bullets))
        if char_blocks:
            cast_dossier_block = (
                "[!!] CAST DOSSIER — canonical retrieval for each active character.\n"
                "Use these excerpts as the source-of-truth for how the character is\n"
                "depicted, written, and behaves. Match the canonical voice exactly.\n\n"
                + "\n\n".join(char_blocks)
            )
    if cast_dossier_block:
        # Insert just after CHARACTER VOICES so per-character data clusters
        # together. Find the index of CHARACTER VOICES block in raw_blocks.
        for i, (label, _) in enumerate(raw_blocks):
            if label == "CHARACTER VOICES":
                raw_blocks.insert(i + 1, ("CAST DOSSIER", cast_dossier_block))
                break

    blocks: list[str] = [content for (_, content) in raw_blocks if content]

    if not blocks:
        return None
    llm_request.append_instructions(blocks)
    logger.info(
        "Storyteller before_model: injected %d block(s) (Phase H structure) "
        "(active chars=%d, chapter=%d)",
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
