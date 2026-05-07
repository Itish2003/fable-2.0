"""Dynamic global-instruction provider for the Storyteller.

Uses the ADK-bundled ``GlobalInstructionPlugin`` directly (no custom
subclass). The provider callable below is passed to its constructor and
runs on ``before_model_callback`` — the framework prepends the returned
string to ``llm_request.config.system_instruction``.

We re-export ``GlobalInstructionPlugin`` so existing imports
(``from src.plugins.global_instruction import GlobalInstructionPlugin``)
continue to resolve to the native class.
"""

from __future__ import annotations

import logging

from google.adk.agents.readonly_context import ReadonlyContext
# Re-exported for callers (e.g. src.app_container, src.nodes.storyteller).
from google.adk.plugins.global_instruction_plugin import GlobalInstructionPlugin

__all__ = ["GlobalInstructionPlugin", "storyteller_instruction_provider"]

logger = logging.getLogger("fable.plugin")


async def storyteller_instruction_provider(ctx: ReadonlyContext) -> str:
    """Builds dynamic tone/pacing notes for the Storyteller agent.

    Returns an empty string for any other agent — the native plugin
    treats falsy return values as a no-op, so non-storyteller agents
    are unaffected.
    """
    if ctx.agent_name != "storyteller":
        return ""

    state = ctx.state

    # Power Debt strain — stored as a dict (event-sourced) or as a Pydantic
    # dump from the WorldBuilder. Read defensively without round-tripping.
    power_debt = state.get("power_debt") or {}
    if isinstance(power_debt, dict):
        power_strain = int(power_debt.get("strain_level", 0))
    else:
        power_strain = int(getattr(power_debt, "strain_level", 0))

    current_mood = state.get("current_mood", "Neutral")
    power_level = state.get("power_level", "street")
    anti_worf_rules = state.get("anti_worf_rules") or {}

    notes: list[str] = []

    if power_strain > 80:
        notes.append(
            "CRITICAL OVERRIDE: The protagonist is severely exhausted (Power"
            " Strain Critical). Emphasize the physical toll of their actions."
            " Limit complex magic or agile movements. Their inner monologue"
            " should reflect fatigue and desperation."
        )
    elif power_strain > 50:
        notes.append(
            "TONE NOTE: The protagonist is feeling the strain of recent"
            " encounters. They are breathing heavily and may hesitate before"
            " using demanding abilities."
        )

    if current_mood == "Tense":
        notes.append(
            "PACING NOTE: The atmosphere is incredibly tense. Use shorter,"
            " sharper sentences. Focus on micro-expressions, ambient silence,"
            " and the feeling of impending conflict."
        )

    if power_level in ("continental", "planetary"):
        notes.append(
            "POWER SCALE NOTE: DEMONSTRATE FULL POWER AT SCALE. DO NOT"
            " artificially limit power to create challenge. The protagonist's"
            " abilities operate on a massive scale; destruction or impact"
            " should be proportionate."
        )

    if anti_worf_rules:
        rules_str = "; ".join(f"{name}: {rule}" for name, rule in anti_worf_rules.items())
        notes.append(
            "ANTI-WORF RULES: Respect the established competence floors —"
            f" {rules_str}. Do not nerf these characters for cheap drama."
        )

    if not notes:
        return ""

    compiled = "\n\n".join(notes)
    logger.info("Injecting dynamic Storyteller notes (Strain: %s)", power_strain)
    return f"[INTERNAL NARRATIVE NOTE]\n{compiled}"
