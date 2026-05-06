import logging
from typing import Any
from google.adk.agents.context import Context

logger = logging.getLogger("fable.recovery")

async def run_recovery(
    ctx: Context,
    node_input: Any,
) -> str:
    """
    Acts as a graceful degradation fallback.
    If the graph hits an unrecoverable state or throws an exception,
    the workflow is routed here. It logs the issue and yields a safe fallback.
    """
    logger.error(f"Recovery Node triggered! Input caused failure: {node_input}")
    
    # In a full implementation, we might try to clean the state or downgrade the model
    # For now, we simply act as a safe end-point to prevent WebSocket crashes.
    
    return "recovered"
