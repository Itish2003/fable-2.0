"""Auditor node — single writer of canonical chapter state.

Reads ``state.temp:storyteller_output`` (parsed StorytellerOutput dict
emitted by the storyteller LlmAgent), validates structurally and
content-wise, and on AUDIT PASSED prepends the deterministic
``# Chapter N`` header and writes the canonical fields
(``last_story_text``, ``last_chapter_meta``). The header arithmetic
comes from ``state.chapter_count`` so the model never has to compute it
(killed bug #1 — frozen "# Chapter 2" header drift).

**Single-writer invariant**: ``last_story_text`` and ``last_chapter_meta``
are ONLY written here, ONLY on AUDIT PASSED. On retry/recovery the
canonical fields retain the LAST PASSED chapter's values, so the
storyteller's PRIOR CHAPTER CONTEXT injection picks up clean tonal
anchoring from the actual previous chapter, not the failed draft.
"""

import logging
from typing import Any, AsyncGenerator

from google.adk.events import Event, EventActions
from google.adk.workflow import node
from google.adk.agents.context import Context

from src.state.chapter_output import validate_tiers
from src.state.models import FableAgentState
from src.utils.leakage_terms import detect_leakage

logger = logging.getLogger("fable.auditor")

# `temp:` prefix bypasses state_schema validation per ADK sessions/state.py:39-40
_AUDIT_RETRY_KEY = "temp:audit_retries"
_MAX_AUDIT_RETRIES = 3


def _heuristic_universes(premise: str) -> list[str]:
    """Conservative fallback when state.universes hasn't been populated."""
    from src.utils.leakage_terms import UNIVERSE_ALIASES
    found: list[str] = []
    p = (premise or "").lower()
    for alias in UNIVERSE_ALIASES:
        if alias in p:
            found.append(alias)
    return found


@node(name="auditor")
async def run_auditor(
    ctx: Context,
    node_input: Any,
) -> AsyncGenerator[Event, None]:
    """Validates structural + content rules; routes "passed" / "failed" / "recovery".

    On PASSED: prepends ``# Chapter N`` header from state.chapter_count
    and writes ``last_story_text`` + ``last_chapter_meta``; increments
    chapter_count; resets per-chapter research counter.
    On FAILED/RECOVERY: leaves canonical state untouched so the next
    storyteller turn picks up the prior chapter as PRIOR CHAPTER CONTEXT.
    """
    try:
        state = FableAgentState(**ctx.state.to_dict())
    except Exception:
        state = FableAgentState()

    # Source: the parsed StorytellerOutput from the LlmAgent's output_key.
    storyteller_output = ctx.state.get("temp:storyteller_output") or {}
    prose = (storyteller_output.get("prose") or "").strip()
    chapter_meta = storyteller_output.get("chapter_meta") or {}

    logger.info(
        "Auditor: prose=%d chars, %d choices, %d questions",
        len(prose),
        len(chapter_meta.get("choices") or []),
        len(chapter_meta.get("questions") or []),
    )

    def _record_failure(reason: str) -> str:
        retries = int(ctx.state.get(_AUDIT_RETRY_KEY, 0)) + 1
        ctx.state[_AUDIT_RETRY_KEY] = retries
        if retries >= _MAX_AUDIT_RETRIES:
            logger.error("AUDIT FAILED (%dx) — %s. Routing to recovery.", retries, reason)
            ctx.state[_AUDIT_RETRY_KEY] = 0
            return "recovery"
        logger.warning("AUDIT FAILED (%dx) — %s. Routing to storyteller for retry.", retries, reason)
        return "failed"

    # 0. Empty prose / empty meta — the storyteller dropped its output.
    if not prose:
        route = _record_failure("empty prose")
        yield Event(actions=EventActions(route=route))
        return
    if not chapter_meta:
        route = _record_failure("empty chapter_meta")
        yield Event(actions=EventActions(route=route))
        return

    # 1. Structural rules — these used to be Pydantic constraints on
    # ChapterOutput; moved to runtime so a model drift routes to retry
    # instead of crashing the agent invocation.
    choices = chapter_meta.get("choices") or []
    questions = chapter_meta.get("questions") or []
    if len(choices) != 4:
        route = _record_failure(f"choices count != 4 (got {len(choices)})")
        yield Event(actions=EventActions(route=route))
        return
    if not (1 <= len(questions) <= 2):
        route = _record_failure(f"questions count out of range (got {len(questions)})")
        yield Event(actions=EventActions(route=route))
        return
    ok, reason = validate_tiers(choices)
    if not ok:
        route = _record_failure(reason)
        yield Event(actions=EventActions(route=route))
        return

    # 2. Epistemic Boundary — prose only (chapter_meta legitimately
    # references forbidden concepts in summary / canon_elements_used).
    prose_lower = prose.lower()
    for concept in state.forbidden_concepts:
        if concept.lower() in prose_lower:
            route = _record_failure(f"Epistemic leak: forbidden concept '{concept}'")
            yield Event(actions=EventActions(route=route))
            return

    # 3. Anti-Worf — prose only.
    defeat_keywords = ["defeated", "beaten", "lost easily", "overpowered by"]
    for char_name, rule in state.anti_worf_rules.items():
        if char_name.lower() in prose_lower:
            for keyword in defeat_keywords:
                if keyword in prose_lower:
                    route = _record_failure(
                        f"Anti-Worf constraint broken for {char_name}. Rule: {rule}"
                    )
                    yield Event(actions=EventActions(route=route))
                    return

    logger.info("AUDIT PASSED: Text is canon-compliant.")

    # ─── SINGLE-WRITER COMMIT (only on PASS) ──────────────────────────────────
    # Prepend the deterministic header from canonical state so the model
    # never has to do arithmetic on chapter_count -- kills bug #1's drift.
    chapter_n = int(ctx.state.get("chapter_count") or 1)
    ctx.state["last_story_text"] = f"# Chapter {chapter_n}\n\n{prose}"
    ctx.state["last_chapter_meta"] = chapter_meta

    # Anti-rut: capture the first ~200 chars of this chapter's prose so the
    # storyteller's ANTI-PATTERN block can show the model recent openings
    # to AVOID repeating. FIFO ring buffer of last 3 entries.
    opening = prose[:200].replace("\n", " ").strip()
    recent_openings = list(ctx.state.get("recent_chapter_openings") or [])
    recent_openings.append(opening)
    ctx.state["recent_chapter_openings"] = recent_openings[-3:]

    # Reset retry counter and advance chapter_count.
    ctx.state[_AUDIT_RETRY_KEY] = 0
    try:
        ctx.state["chapter_count"] = chapter_n + 1
        logger.info("Chapter %d audited; advancing chapter_count -> %d", chapter_n, chapter_n + 1)
    except Exception:
        pass

    # Reset per-chapter trigger_research budget so the next chapter starts
    # with a fresh 2-call cap. Lazy import keeps the auditor decoupled
    # from research_tools.
    from src.tools.research_tools import reset_research_counter
    reset_research_counter(ctx.state)

    # Phase G: source-universe leakage scan. Soft warning only.
    story_universes = ctx.state.get("universes") or []
    if not story_universes:
        premise = (ctx.state.get("story_premise") or "")[:2000]
        story_universes = _heuristic_universes(premise)
    leaks = detect_leakage(prose, story_universes)
    if leaks:
        log = list(ctx.state.get("violation_log") or [])
        for leak in leaks:
            log.append(leak.to_dict())
        ctx.state["violation_log"] = log
        logger.warning(
            "LEAKAGE: %d source-universe term(s) detected: %s",
            len(leaks),
            ", ".join(f"{l.universe_origin}:{l.term}" for l in leaks[:6]),
        )

    yield Event(actions=EventActions(route="passed"))
