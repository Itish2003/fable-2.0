"""Auditor node — consumes the typed ``state.storyteller_output``.

No more fenced-JSON parsing (``parse_chapter_tail`` is dead code; the
storyteller now emits a Pydantic-validated StorytellerOutput via
``output_schema``). The auditor reads the parsed dict, validates the
structural rules that USED to live as Pydantic constraints on
ChapterOutput (4 choices spanning all 4 tiers exactly, 1-2 questions),
then runs the deterministic content audits (epistemic leak, anti-Worf,
source-universe leakage scan).

Writing ``last_story_text`` and ``last_chapter_meta`` is now
``storyteller_merge_node``'s job (it prepends the deterministic
``# Chapter N`` header from ``state.chapter_count``); the auditor only
increments ``chapter_count`` on AUDIT PASSED and runs the per-chapter
research budget reset.

The ``reset_archivist_counters`` call is gone — the per-chapter tool-cap
machinery was deleted with the archivist rewrite.
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

    Reads ``state.storyteller_output`` (parsed by the storyteller
    LlmAgent) and ``state.last_story_text`` (composed by
    ``storyteller_merge`` with the deterministic header). Does not parse
    raw text and does not write either of those fields.
    """
    try:
        state = FableAgentState(**ctx.state.to_dict())
    except Exception:
        state = FableAgentState()

    # Source: the parsed StorytellerOutput from the LlmAgent's output_key.
    storyteller_output = ctx.state.get("temp:storyteller_output") or {}
    chapter_meta = storyteller_output.get("chapter_meta") or {}
    story_text = (ctx.state.get("last_story_text") or "").strip()

    logger.info(
        "Auditor: prose=%d chars, %d choices, %d questions",
        len(story_text),
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
    if not story_text:
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
    story_lower = story_text.lower()
    for concept in state.forbidden_concepts:
        if concept.lower() in story_lower:
            route = _record_failure(f"Epistemic leak: forbidden concept '{concept}'")
            yield Event(actions=EventActions(route=route))
            return

    # 3. Anti-Worf — prose only.
    defeat_keywords = ["defeated", "beaten", "lost easily", "overpowered by"]
    for char_name, rule in state.anti_worf_rules.items():
        if char_name.lower() in story_lower:
            for keyword in defeat_keywords:
                if keyword in story_lower:
                    route = _record_failure(
                        f"Anti-Worf constraint broken for {char_name}. Rule: {rule}"
                    )
                    yield Event(actions=EventActions(route=route))
                    return

    logger.info("AUDIT PASSED: Text is canon-compliant.")

    # Reset retry counter and advance chapter_count. last_story_text /
    # last_chapter_meta were already written by storyteller_merge.
    ctx.state[_AUDIT_RETRY_KEY] = 0
    try:
        prev = int(ctx.state.get("chapter_count", 1) or 1)
        ctx.state["chapter_count"] = prev + 1
        logger.info("Chapter %d audited; advancing chapter_count -> %d", prev, prev + 1)
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
    leaks = detect_leakage(story_text, story_universes)
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
