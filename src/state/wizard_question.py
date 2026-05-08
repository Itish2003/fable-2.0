"""Pydantic schema for the setup-wizard's clarifying question.

The wizard runs once per story (Phase D) inside ``world_builder`` to
gather one laser-focused answer about fusion-mechanics, identity, or
timeline before research kicks off. Replacing the previous manual
``if not isinstance(data, dict) or 'question' not in data`` schema gate
with this Pydantic model gets the same safety as ADK's output_schema
path — the model's JSON either parses cleanly or the wizard step
falls through gracefully.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class WizardQuestion(BaseModel):
    question: str = Field(
        description=(
            "One sentence, specific, targeting a fusion-mechanic / identity / "
            "timeline ambiguity in the user's framework."
        )
    )
    context: str = Field(
        default="",
        description="One sentence explaining why this ambiguity matters for the story.",
    )
    options: list[str] = Field(
        default_factory=list,
        description="3-5 plausible options the user can pick from.",
    )


__all__ = ["WizardQuestion"]
