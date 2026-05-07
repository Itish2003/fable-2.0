"""Strain-tracking telemetry plugin.

Observes ``after_model_callback`` for the Storyteller and converts
heavy reasoning overhead into ``power_debt.strain_level`` increments.
Mutates state via plain dict assignment so the change is event-sourced
and survives resume — no Pydantic round-trip.

Raw token-usage logging is delegated to ADK's bundled ``LoggingPlugin``
(registered in ``src.app_container``).
"""

from __future__ import annotations

import logging
from typing import Optional

from google.adk.agents.callback_context import CallbackContext
from google.adk.models.llm_response import LlmResponse
from google.adk.plugins.base_plugin import BasePlugin

logger = logging.getLogger("fable.telemetry")

# Reasoning-token budget below which we don't accrue strain.
REASONING_STRAIN_FLOOR = 50


class TelemetryPlugin(BasePlugin):
    """Adds narrative strain to ``power_debt`` when the Storyteller burns
    significant reasoning tokens.
    """

    def __init__(self) -> None:
        super().__init__(name="fable_telemetry_plugin")

    async def after_model_callback(
        self,
        *,
        callback_context: CallbackContext,
        llm_response: LlmResponse,
    ) -> Optional[LlmResponse]:
        if callback_context.agent_name != "storyteller":
            return None

        usage = getattr(llm_response, "usage_metadata", None)
        if usage is None:
            return None

        reasoning_tokens = getattr(usage, "reasoning_token_count", 0) or 0
        if reasoning_tokens <= REASONING_STRAIN_FLOOR:
            return None

        # Dict-based state mutation — event-sourced, resume-safe.
        power_debt = dict(callback_context.state.get("power_debt") or {})
        current_strain = int(power_debt.get("strain_level", 0))
        new_strain = current_strain + (reasoning_tokens // 50)
        power_debt["strain_level"] = new_strain
        # Preserve recent_feats if present; default to [] if not.
        power_debt.setdefault("recent_feats", [])
        callback_context.state["power_debt"] = power_debt

        logger.warning(
            "Heavy reasoning overhead (%s tokens) → strain %s -> %s",
            reasoning_tokens,
            current_strain,
            new_strain,
        )
        return None
