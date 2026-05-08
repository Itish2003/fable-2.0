import json
import logging
from typing import Any, AsyncGenerator

from google.adk.workflow import node
from google.adk.agents.context import Context
from google.adk.events.request_input import RequestInput
from google.adk.agents.llm_agent import LlmAgent

logger = logging.getLogger("fable.choice_generator")

# Allowed tier values for normal-path choices is always None;
# the suspicion plugin (Agent 1) overrides with these strings.
_ALLOWED_TIERS = {None, "oblivious", "uneasy", "suspicious", "breakthrough"}


def create_choice_generator() -> LlmAgent:
    return LlmAgent(
        name="choice_generator",
        description="Generates 4 interactive choices based on the latest story chapter.",
        model="gemini-3.1-flash-lite-preview",
        instruction="""
        You are a Choice Generator for an interactive story.
        Based on the current narrative state, generate exactly 4 compelling choices for the protagonist.

        OUTPUT FORMAT:
        Return ONLY strict JSON with the exact shape:
        {
          "prompt": "<short prompt to the player>",
          "choices": [
            {"text": "<choice 1>", "tier": null},
            {"text": "<choice 2>", "tier": null},
            {"text": "<choice 3>", "tier": null},
            {"text": "<choice 4>", "tier": null}
          ]
        }

        - Always emit EXACTLY 4 choice objects.
        - Always set "tier" to null on every choice. The Suspicion plugin overrides
          this downstream when applicable; you must not invent tier strings.
        - Do NOT use markdown code fences. Do NOT add conversational text.
        """,
    )


def _normalize_choice(raw: Any) -> dict:
    """Coerce a single LLM-emitted choice into {text, tier} with safe defaults."""
    if isinstance(raw, dict):
        text = str(raw.get("text", "")).strip()
        tier = raw.get("tier", None)
        if tier not in _ALLOWED_TIERS:
            tier = None
        return {"text": text or "Continue", "tier": tier}
    # Backwards-compat: a bare string => normal-path choice
    return {"text": str(raw).strip() or "Continue", "tier": None}


def _default_payload() -> dict:
    return {
        "prompt": "What do you do next?",
        "choices": [
            {"text": "Continue", "tier": None},
            {"text": "Investigate", "tier": None},
            {"text": "Retreat", "tier": None},
            {"text": "Use Power", "tier": None},
        ],
    }


@node(name="choice_generator_node", rerun_on_resume=True)
async def choice_generator_node(ctx: Context, node_input: Any) -> AsyncGenerator[Any, None]:
    """
    Parses the typed JSON object from the Choice Generator LLM and yields a
    RequestInput to suspend the graph and wait for the user.
    """
    interrupt_id = "user_choice_selection"
    resume_payload = ctx.resume_inputs.get(interrupt_id)

    if resume_payload:
        logger.info(f"Received choice selection from frontend: {resume_payload}")
        # Graph resumed, save the user input into state
        payload_val = resume_payload.get("payload", "") if isinstance(resume_payload, dict) else str(resume_payload)
        ctx.state["last_user_choice"] = payload_val
        return

    text_output = ""
    payload = _default_payload()

    try:
        if hasattr(node_input, "content") and node_input.content and node_input.content.parts:
            text_output = node_input.content.parts[0].text.strip()

            # Clean markdown if present
            if text_output.startswith("```json"):
                text_output = text_output.split("```json")[1].split("```")[0].strip()
            elif text_output.startswith("```"):
                text_output = text_output.split("```")[1].split("```")[0].strip()

            parsed = json.loads(text_output)

            if isinstance(parsed, dict) and isinstance(parsed.get("choices"), list):
                # New schema: {prompt, choices: [{text, tier}]}
                prompt = str(parsed.get("prompt") or "What do you do next?").strip()
                choices = [_normalize_choice(c) for c in parsed["choices"]][:4]
                # Always emit exactly 4 choices; pad if model under-delivered.
                while len(choices) < 4:
                    choices.append({"text": "Continue", "tier": None})
                payload = {"prompt": prompt or "What do you do next?", "choices": choices}
                logger.info(f"Generated {len(choices)} choices successfully (new schema).")
            elif isinstance(parsed, list) and len(parsed) > 0:
                # Backwards-compat: legacy array-of-strings format.
                choices = [_normalize_choice(c) for c in parsed][:4]
                while len(choices) < 4:
                    choices.append({"text": "Continue", "tier": None})
                payload = {"prompt": "What do you do next?", "choices": choices}
                logger.info(f"Generated {len(choices)} choices successfully (legacy schema).")
    except Exception as e:
        logger.error(f"Failed to parse Choice Generator JSON: {e}. Output was: {text_output}")

    yield RequestInput(
        interrupt_id=interrupt_id,
        message=json.dumps(payload),
    )
