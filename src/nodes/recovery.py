import logging
from typing import Any
from google.adk.agents.context import Context

logger = logging.getLogger("fable.recovery")

_RECOVERY_PROSE = (
    "The narrative weave momentarily destabilizes. The threads tangle, "
    "and the next moment hangs in unresolved silence. Choose how the "
    "story finds its footing again."
)


async def run_recovery(
    ctx: Context,
    node_input: Any,
) -> str:
    """Graceful-degradation fallback after 3 consecutive auditor failures.

    Skips the broken turn cleanly:
    1. Writes a brief fallback into ``last_story_text`` so downstream
       consumers have anchoring context.
    2. **Clears ``last_chapter_meta``** so the WS runner's chapter_meta
       emit-path falls through to the synthetic fallback choices block
       instead of shipping the prior chapter's stale choices alongside
       the recovery prose.
    3. Resets the auditor retry counter (``temp:audit_retries``).
    4. Returns; recovery_node is TERMINAL (no outgoing edges) -- the
       runner emits chapter_meta + state_update + turn_complete after
       the workflow exits, letting the player redirect the story.
    """
    logger.error(
        "Recovery node triggered after auditor failures. node_input=%r",
        node_input,
    )

    ctx.state["last_story_text"] = _RECOVERY_PROSE
    ctx.state["last_chapter_meta"] = None
    ctx.state["temp:audit_retries"] = 0

    return "recovered"
