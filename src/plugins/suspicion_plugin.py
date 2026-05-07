"""Suspicion Engine plugin — steers the choice_generator when the latest
chapter drifts close to a forbidden concept the POV character should not know.

Implementation notes:
  - Hooks ``before_model_callback`` (NOT ``before_agent_callback``) so we can
    mutate ``llm_request.config.system_instruction`` rather than replacing
    agent output.
  - Filters by ``callback_context.agent_name == "choice_generator"``.
  - Caches per-concept embeddings in ``app:forbidden_concept_embeddings``
    state (the ``app:`` prefix persists across sessions); the story
    embedding is computed fresh each turn.
  - When triggered, prepends a SUSPICION PROTOCOL preamble that overrides
    the choice_generator's default schema with the four-tier output
    contract: oblivious / uneasy / suspicious / breakthrough.
"""

from __future__ import annotations

import logging
from typing import Optional

from google.adk.agents.callback_context import CallbackContext
from google.adk.models.llm_request import LlmRequest
from google.adk.models.llm_response import LlmResponse
from google.adk.plugins.base_plugin import BasePlugin

from src.services.embedding_service import get_embedding

logger = logging.getLogger("fable.suspicion_plugin")

# Cosine-similarity threshold above which the protocol activates.
SIMILARITY_THRESHOLD = 0.78

# State key (app:-scoped so it survives session resumes).
EMBEDDING_CACHE_KEY = "app:forbidden_concept_embeddings"

SUSPICION_PROTOCOL_PREAMBLE = (
    "[SUSPICION PROTOCOL ACTIVE]\n"
    "The protagonist is standing right next to a forbidden secret:"
    " '{concept}'. The POV character does not know this concept, but the"
    " latest chapter has drifted close to it.\n\n"
    "OUTPUT OVERRIDE — IGNORE the default choice schema. Return ONLY a"
    " strict JSON object with this exact shape, no markdown fences:\n"
    '{{"prompt": "<one-line prompt for the user>", "choices": ['
    '{{"text": "<choice text>", "tier": "oblivious"}},'
    ' {{"text": "<choice text>", "tier": "uneasy"}},'
    ' {{"text": "<choice text>", "tier": "suspicious"}},'
    ' {{"text": "<choice text>", "tier": "breakthrough"}}'
    "]}}\n"
    "Exactly four entries, in that tier order:\n"
    "  1. oblivious   — complete obliviousness; the character notices"
    " nothing.\n"
    "  2. uneasy      — vague unease; an unexplained instinct.\n"
    "  3. suspicious  — active suspicion; the character starts piecing"
    " things together but does NOT name the forbidden concept.\n"
    "  4. breakthrough — the character attempts a direct revelation, naming"
    " or confronting the forbidden concept head-on.\n"
)


def _cosine_similarity(v1: list[float], v2: list[float]) -> float:
    dot_product = sum(a * b for a, b in zip(v1, v2))
    norm_v1 = sum(a * a for a in v1) ** 0.5
    norm_v2 = sum(b * b for b in v2) ** 0.5
    if norm_v1 == 0 or norm_v2 == 0:
        return 0.0
    return dot_product / (norm_v1 * norm_v2)


class SuspicionPlugin(BasePlugin):
    """Prepends a SUSPICION PROTOCOL preamble to ``choice_generator`` LLM
    requests when the latest story prose is semantically close to a
    forbidden concept.
    """

    def __init__(self) -> None:
        super().__init__(name="suspicion_plugin")

    async def before_model_callback(
        self,
        *,
        callback_context: CallbackContext,
        llm_request: LlmRequest,
    ) -> Optional[LlmResponse]:
        if callback_context.agent_name != "choice_generator":
            return None

        state = callback_context.state
        last_story_text = state.get("last_story_text", "")
        forbidden_concepts = state.get("forbidden_concepts") or []

        if not last_story_text or not forbidden_concepts:
            return None

        # Concept-embedding cache (app:-scoped; rebuilt incrementally).
        cache: dict[str, list[float]] = dict(state.get(EMBEDDING_CACHE_KEY) or {})
        cache_dirty = False

        story_embedding = await get_embedding(last_story_text)

        triggered_concept: Optional[str] = None
        for concept in forbidden_concepts:
            concept_embedding = cache.get(concept)
            if concept_embedding is None:
                concept_embedding = await get_embedding(concept)
                cache[concept] = concept_embedding
                cache_dirty = True

            similarity = _cosine_similarity(story_embedding, concept_embedding)
            logger.info("Suspicion check for '%s': %.3f", concept, similarity)
            if similarity > SIMILARITY_THRESHOLD:
                triggered_concept = concept
                break

        if cache_dirty:
            state[EMBEDDING_CACHE_KEY] = cache

        if triggered_concept is None:
            return None

        logger.warning(
            "Suspicion Protocol activated for concept: %s", triggered_concept
        )

        preamble = SUSPICION_PROTOCOL_PREAMBLE.format(concept=triggered_concept)

        # Prepend — preserve any existing system_instruction so the agent's
        # baseline prompt remains visible after the protocol header.
        existing = llm_request.config.system_instruction
        if not existing:
            llm_request.config.system_instruction = preamble
        elif isinstance(existing, str):
            llm_request.config.system_instruction = f"{preamble}\n\n{existing}"
        else:  # Iterable of strings
            llm_request.config.system_instruction = [preamble, *list(existing)]

        return None
