import logging
from typing import Any, Optional

from google.adk.plugins.base_plugin import BasePlugin
from google.adk.agents.callback_context import CallbackContext
from google.adk.models.llm_response import LlmResponse

logger = logging.getLogger("fable.telemetry")

class TelemetryPlugin(BasePlugin):
    """
    Observes LLM UsageMetadata for each agent turn.
    Logs telemetry (prompt tokens, reasoning tokens) and adjusts
    the narrative strain (power_debt) dynamically.
    """
    
    def __init__(self):
        super().__init__(name="fable_telemetry_plugin")

    async def after_model_callback(
        self,
        *,
        callback_context: CallbackContext,
        llm_response: LlmResponse
    ) -> Optional[LlmResponse]:
        """Called after a response is received from the model."""
        
        usage = getattr(llm_response, "usage_metadata", None)
        if usage:
            p_tokens = getattr(usage, "prompt_token_count", 0)
            c_tokens = getattr(usage, "cached_content_token_count", 0)
            # Check for Gemini 1.5 Pro/Flash Reasoning Tokens
            r_tokens = getattr(usage, "reasoning_token_count", 0)
            
            logger.info(
                f"[Telemetry] Agent: {callback_context.agent_name} | "
                f"Prompt: {p_tokens} (Cached: {c_tokens}) | "
                f"Reasoning: {r_tokens}"
            )
            
            # Dynamic Strain Calculation
            if callback_context.agent_name == "storyteller" and r_tokens > 50:
                try:
                    state = FableAgentState(**{k: callback_context.state[k] for k in callback_context.state._value.keys() | callback_context.state._delta.keys()})
                    if hasattr(state, "power_debt"):
                        logger.warning(
                            f"Heavy reasoning overhead detected ({r_tokens} tokens). "
                            "Applying Power Debt strain to protagonist."
                        )
                        state.power_debt.strain_level += (r_tokens // 50)
                        # Push back to context state to trigger delta
                        callback_context.state["power_debt"] = state.power_debt.model_dump()
                except Exception as e:
                    logger.error(f"Failed to apply telemetry strain: {e}")
                    
        return None
