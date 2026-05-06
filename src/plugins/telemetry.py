import logging
from typing import Any

from google.adk.plugins.base_plugin import BasePlugin
from google.adk.agents.callback_context import CallbackContext

logger = logging.getLogger("fable.telemetry")

class TelemetryPlugin(BasePlugin):
    """
    Observes LLM UsageMetadataChunk for each agent turn.
    Logs telemetry (prompt tokens, reasoning tokens) and adjusts
    the narrative strain (power_debt) dynamically.
    """
    
    def __init__(self):
        super().__init__(name="fable_telemetry_plugin")

    async def run_after_agent_callback(
        self,
        *,
        agent: Any,
        callback_context: CallbackContext,
        event: Any,
    ) -> None:
        """Called after an agent yields an event."""
        
        # In ADK 2.0 Beta, the Event contains model_responses for LLM events
        if hasattr(event, "model_responses") and event.model_responses:
            last_response = event.model_responses[-1]
            
            # Extract usage metadata natively provided by Gemini API
            usage = getattr(last_response, "usage_metadata", None)
            if usage:
                p_tokens = getattr(usage, "prompt_token_count", 0)
                c_tokens = getattr(usage, "cached_content_token_count", 0)
                # Some API versions use cached_prompt_token_count
                if not c_tokens and hasattr(usage, "cached_prompt_token_count"):
                    c_tokens = usage.cached_prompt_token_count
                
                # Check for Gemini 1.5 Pro/Flash Reasoning Tokens
                r_tokens = getattr(usage, "reasoning_token_count", 0)
                
                logger.info(
                    f"[Telemetry] Agent: {agent.name} | "
                    f"Prompt: {p_tokens} (Cached: {c_tokens}) | "
                    f"Reasoning: {r_tokens}"
                )
                
                # Dynamic Strain Calculation: 
                # If the Storyteller had to use heavy reasoning overhead, 
                # we conceptually translate this into the protagonist straining their abilities.
                if agent.name == "storyteller" and r_tokens > 50:
                    # Attempt to safely get and update the State
                    inv_ctx = callback_context.context.get_invocation_context()
                    state = inv_ctx.agent_states.get(agent.name)
                    if state and hasattr(state, "power_debt"):
                        logger.warning(
                            f"Heavy reasoning overhead detected ({r_tokens} tokens). "
                            "Applying Power Debt strain to protagonist."
                        )
                        # We increment the strain dynamically behind the scenes
                        state.power_debt.strain_level += (r_tokens // 50)
