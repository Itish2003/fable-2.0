from __future__ import annotations

import logging
from typing import Optional

from google.adk.agents.callback_context import CallbackContext
from google.adk.agents.llm_agent import LlmAgent
from google.adk.models.llm_request import LlmRequest
from google.adk.models.llm_response import LlmResponse

from src.tools.lore_lookup_tool import lore_lookup, retrieve_lore

# We use the highly efficient gemini-3.1-flash-lite-preview model as requested
STORYTELLER_MODEL = "gemini-3.1-flash-lite-preview"

logger = logging.getLogger("fable.storyteller")


async def _inject_active_character_lore(
    callback_context: CallbackContext,
    llm_request: LlmRequest,
) -> Optional[LlmResponse]:
    """``before_model_callback`` for the Storyteller.

    Pre-fetches lore for every name in ``state["active_characters"]`` and
    appends a "Known facts about active characters" block to the system
    instruction via ``llm_request.append_instructions`` -- the canonical
    mutation API on :class:`LlmRequest` (see
    ``google.adk.models.llm_request.LlmRequest.append_instructions``).

    Reuses :func:`src.tools.lore_lookup_tool.retrieve_lore` so the on-demand
    tool and the pre-injection share one retrieval code path.

    No-op when ``active_characters`` is empty or no matches come back.
    Returning ``None`` lets the LLM call proceed normally (ADK contract).
    """
    state = callback_context.state
    active_characters = state.get("active_characters") or {}
    if not active_characters:
        return None

    blocks: list[str] = []
    for name in active_characters.keys():
        matches = await retrieve_lore(name)
        if not matches:
            continue
        bullets: list[str] = []
        for m in matches:
            attrs = m.get("attributes") or {}
            attrs_str = f" attributes={attrs}" if attrs else ""
            bullets.append(f"- {m.get('chunk_text', '').strip()}{attrs_str}")
        blocks.append(f"## {name}\n" + "\n".join(bullets))

    if not blocks:
        return None

    payload = "Known facts about active characters:\n\n" + "\n\n".join(blocks)
    llm_request.append_instructions([payload])
    logger.info(
        "Storyteller before_model: injected lore for %d character(s)",
        len(blocks),
    )
    return None


def create_storyteller_node() -> LlmAgent:
    """
    Creates the Storyteller Node.
    In ADK 2.0 Beta, an LlmAgent can be passed directly as a sub_node in a Workflow.
    This node generates the primary prose.
    Formatting and Tone are handled by external plugins and schema enforcements.

    Knowledge management follows the ADK 2.0 idiom: a ``before_model_callback``
    pre-injects lore for currently active characters, and the ``lore_lookup``
    tool lets the model pull additional lore on demand. Tool-calling stays in
    the default ``mode='AUTO'`` -- ``mode='ANY'`` forces a function call every
    turn and produces infinite loops (see ``src/nodes/archivist.py`` for the
    same lesson).
    """
    return LlmAgent(
        name="storyteller",
        description="Generates the core narrative prose.",
        model=STORYTELLER_MODEL,
        instruction=(
            "You are a master storyteller writing a crossover narrative. "
            "Write the next chapter based on the user's choices. "
            "Focus entirely on rich, evocative prose. Do not output raw JSON or internal state tags. "
            "When you reference a character, faction, or concept whose details you're unsure of, "
            "call `lore_lookup` first to retrieve canonical facts."
        ),
        tools=[lore_lookup],
        before_model_callback=_inject_active_character_lore,
    )
