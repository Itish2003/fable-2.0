import logging
from typing import Any, AsyncGenerator

from google.adk.workflow import node
from google.adk.agents.context import Context
from google.adk.events import Event, EventActions

from src.state.models import FableAgentState
from src.state.chapter_output import parse_chapter_tail

logger = logging.getLogger("fable.auditor")

# Counter is stored under a `temp:` prefixed key; the `:` prefix bypasses
# state_schema validation per sessions/state.py:39-40, so we don't need to
# add a field to FableAgentState for what is purely a per-loop retry count.
_AUDIT_RETRY_KEY = "temp:audit_retries"
_MAX_AUDIT_RETRIES = 3


@node(name="auditor")
async def run_auditor(
    ctx: Context,
    node_input: Any,
) -> AsyncGenerator[Event, None]:
    """
    Evaluates Epistemic Boundaries and Anti-Worf rules.
    If the Storyteller's output violates core constraints, this node
    emits a 'failed' route and the graph routes backward. After
    _MAX_AUDIT_RETRIES consecutive failures, it emits 'recovery' to
    hand off to the recovery node.

    Also splits the Storyteller's prose-plus-fenced-JSON output into the
    player-facing prose (written to ``state.last_story_text``) and the
    structured ChapterOutput dict (written to ``state.last_chapter_meta``)
    consumed downstream by ``user_choice_input_node``.
    """
    # Fetch state from the public to_dict() snapshot.
    try:
        state = FableAgentState(**ctx.state.to_dict())
    except Exception:
        state = FableAgentState()  # Fallback

    raw_text = ""
    if isinstance(node_input, Event) and node_input.content:
        raw_text = node_input.content.parts[0].text if node_input.content.parts else ""
    elif isinstance(node_input, dict) and "text" in node_input:
        raw_text = node_input["text"]
    elif isinstance(node_input, str):
        raw_text = node_input

    # Split the storyteller's output: prose for the audit + reader, and the
    # ChapterOutput JSON tail for the choice picker. parse_chapter_tail
    # gracefully returns (raw_text, None) on failure (no fence / malformed
    # JSON / schema mismatch).
    prose, chapter_meta = parse_chapter_tail(raw_text)
    story_text = prose

    logger.info(
        "Auditor analyzing prose length: %d (raw input %d chars; chapter_meta=%s)",
        len(story_text), len(raw_text), "yes" if chapter_meta else "no",
    )

    def _record_failure(reason: str) -> str:
        """Bump the retry counter and return the route to take next."""
        retries = int(ctx.state.get(_AUDIT_RETRY_KEY, 0)) + 1
        ctx.state[_AUDIT_RETRY_KEY] = retries
        if retries >= _MAX_AUDIT_RETRIES:
            logger.error(
                f"AUDIT FAILED ({retries}x) — {reason}. Routing to recovery."
            )
            # Reset so a fresh failure cycle starts after recovery handles it.
            ctx.state[_AUDIT_RETRY_KEY] = 0
            return "recovery"
        logger.warning(
            f"AUDIT FAILED ({retries}x) — {reason}. Routing to storyteller for retry."
        )
        return "failed"

    # 1. Epistemic Boundary Check (Dynamic) — run on prose only so we don't
    # trip on forbidden concepts that legitimately appear inside the
    # ChapterOutput JSON (e.g. summary, canon_elements_used).
    story_lower = story_text.lower()
    for concept in state.forbidden_concepts:
        if concept.lower() in story_lower:
            route = _record_failure(f"Epistemic leak: forbidden concept '{concept}'")
            yield Event(actions=EventActions(route=route))
            return

    # 2. Anti-Worf Check (Dynamic)
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

    # Persist the prose for downstream nodes (Summarizer, SuspicionPlugin).
    # Stripping the JSON tail here means consumers see only what the player
    # sees. Reader-facing text == auditor-checked text == summarizer input.
    ctx.state["last_story_text"] = story_text

    # Persist the structured tail so user_choice_input can surface its
    # typed choices + meta-questions. None when the model dropped the tail
    # (defensive: user_choice_input has fallback choices).
    if chapter_meta is not None:
        ctx.state["last_chapter_meta"] = chapter_meta.model_dump()
    else:
        # Don't overwrite a previous turn's meta with None; only clear it
        # when a parse explicitly fails so the next turn can detect drift.
        ctx.state["last_chapter_meta"] = None

    # Reset the retry counter so future failures start fresh.
    ctx.state[_AUDIT_RETRY_KEY] = 0

    # Explicitly yield the 'passed' route so the Workflow Graph can follow the edge
    yield Event(actions=EventActions(route="passed"))
