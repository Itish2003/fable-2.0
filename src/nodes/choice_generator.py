import json
import logging
from typing import Any, AsyncGenerator

from google.adk.workflow import node
from google.adk.agents.context import Context
from google.adk.events.request_input import RequestInput
from google.adk.agents.llm_agent import LlmAgent
from google.adk.agents.llm_agent_config import LlmAgentConfig

logger = logging.getLogger("fable.choice_generator")

def create_choice_generator() -> LlmAgent:
    config = LlmAgentConfig(
        name="choice_generator",
        description="Generates 4 interactive choices based on the latest story chapter.",
        model="gemini-3.1-flash-lite-preview",
        instruction="""
        You are a Choice Generator for an interactive story.
        Based on the current narrative state, generate exactly 4 compelling choices for the protagonist.
        
        OUTPUT FORMAT:
        Return ONLY a strict JSON array of 4 strings representing the choices.
        Do not use markdown blocks. Do not add conversational text.
        
        Example:
        ["Investigate the glowing artifact", "Attack the guard", "Sneak past", "Talk to the merchant"]
        """
    )
    return LlmAgent.from_config(config, config_abs_path="")

@node(name="choice_generator_node", rerun_on_resume=True)
async def choice_generator_node(ctx: Context, node_input: Any) -> AsyncGenerator[Any, None]:
    """
    Parses the JSON array from the Choice Generator LLM and yields a RequestInput 
    to suspend the graph and wait for the user.
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
    choices = ["Continue", "Investigate", "Retreat", "Use Power"]
    
    try:
        if hasattr(node_input, "content") and node_input.content and node_input.content.parts:
            text_output = node_input.content.parts[0].text.strip()
            
            # Clean markdown if present
            if text_output.startswith("```json"):
                text_output = text_output.split("```json")[1].split("```")[0].strip()
            elif text_output.startswith("```"):
                text_output = text_output.split("```")[1].split("```")[0].strip()
                
            parsed = json.loads(text_output)
            if isinstance(parsed, list) and len(parsed) > 0:
                choices = [str(c) for c in parsed][:4]
                logger.info(f"Generated {len(choices)} choices successfully.")
    except Exception as e:
        logger.error(f"Failed to parse Choice Generator JSON: {e}. Output was: {text_output}")
        
    yield RequestInput(
        interrupt_id=interrupt_id,
        message=json.dumps({"prompt": "What do you do next?", "choices": choices})
    )
