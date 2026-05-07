import logging
from typing import Optional, Any
from google.adk.plugins.base_plugin import BasePlugin
from google.adk.agents.callback_context import CallbackContext
from google.genai import types

from src.services.embedding_service import get_embedding

logger = logging.getLogger("fable.suspicion_plugin")

def cosine_similarity(v1: list[float], v2: list[float]) -> float:
    dot_product = sum(a * b for a, b in zip(v1, v2))
    norm_v1 = sum(a * a for a in v1) ** 0.5
    norm_v2 = sum(b * b for b in v2) ** 0.5
    if norm_v1 == 0 or norm_v2 == 0:
        return 0.0
    return dot_product / (norm_v1 * norm_v2)

class SuspicionPlugin(BasePlugin):
    def __init__(self):
        super().__init__(name="suspicion_plugin")
        
    async def before_agent_callback(
        self,
        *,
        agent: Any,
        callback_context: CallbackContext,
        **kwargs
    ) -> Optional[types.Content]:
        if agent.name != "choice_generator":
            return None
            
        last_story_text = callback_context.context.state.get("last_story_text", "")
        forbidden_concepts = callback_context.context.state.get("forbidden_concepts", [])
        
        if not last_story_text or not forbidden_concepts:
            return None
            
        try:
            story_embedding = await get_embedding(last_story_text)
            
            for concept in forbidden_concepts:
                concept_embedding = await get_embedding(concept)
                similarity = cosine_similarity(story_embedding, concept_embedding)
                
                logger.info(f"Suspicion check for '{concept}': {similarity}")
                
                if similarity > 0.78:
                    prompt = (
                        f"[SUSPICION PROTOCOL ACTIVE]: The protagonist is standing right next to "
                        f"a forbidden secret: {concept}. Generate exactly 4 choices on a spectrum "
                        f"of awareness: 1. Complete Obliviousness. 2. Vague Unease. 3. Active Suspicion. "
                        f"4. Breakthrough (attempt a direct revelation)."
                    )
                    logger.warning(f"Suspicion Protocol activated for concept: {concept}")
                    return types.Content(
                        role="user",
                        parts=[types.Part.from_text(text=prompt)]
                    )
        except Exception as e:
            logger.error(f"Error in SuspicionPlugin: {e}")
            
        return None
