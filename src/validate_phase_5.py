import asyncio
import os
import sys

# Ensure project root is in path for imports
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from src.nodes.world_builder import run_world_builder
from google.adk.events.request_input import RequestInput
from google.adk.agents.context import Context
from unittest.mock import MagicMock

async def validate_phase_5():
    print("\n--- PHASE 5 VALIDATION ---")
    
    # 1. First Pass: Expected to yield RequestInput for Genre
    print("\n[1/3] Starting WorldBuilder (Turn 1)...")
    ctx = MagicMock(spec=Context)
    ctx.state = {}
    ctx.resume_inputs = {}
    
    # Since run_world_builder is a @node, we access the underlying function
    agen_1 = run_world_builder._func(ctx=ctx, node_input=None)
    
    result_1 = await agen_1.__anext__()
    print(f"  -> Emitted: {type(result_1).__name__}")
    print(f"  -> Message: {result_1.message}")
    assert isinstance(result_1, RequestInput)
    assert result_1.interrupt_id == "setup_genre"

    # 2. Second Pass: Resuming with Genre answer, expect RequestInput for Protagonist
    print("\n[2/3] Resuming WorldBuilder with Genre (Turn 2)...")
    ctx.resume_inputs = {"setup_genre": "Cyberpunk Mahouka Crossover"}
    
    agen_2 = run_world_builder._func(ctx=ctx, node_input=None)
    result_2 = await agen_2.__anext__()
    print(f"  -> Emitted: {type(result_2).__name__}")
    print(f"  -> Message: {result_2.message}")
    assert isinstance(result_2, RequestInput)
    assert result_2.interrupt_id == "setup_protagonist"

    # 3. Third Pass: Resuming with Protagonist answer, expect Completion
    print("\n[3/3] Resuming WorldBuilder with Protagonist (Turn 3)...")
    ctx.resume_inputs = {
        "setup_genre": "Cyberpunk Mahouka Crossover", 
        "setup_protagonist": "Can rewrite gravity vectors"
    }
    
    agen_3 = run_world_builder._func(ctx=ctx, node_input=None)
    result_3 = await agen_3.__anext__()
    print(f"  -> Emitted: {result_3}")
    assert isinstance(result_3, dict)
    assert result_3["setup_status"] == "complete"
    assert result_3["universe"] == "Cyberpunk Mahouka Crossover"

    print("\n✓ Interactive State Machine successfully transitions through HITL phases.")
    print("\n--- VALIDATION COMPLETE ---")

if __name__ == "__main__":
    asyncio.run(validate_phase_5())
