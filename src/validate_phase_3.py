import asyncio
import os
import sys

# Ensure project root is in path for imports
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from src.state.models import FableAgentState, PowerDebt, CharacterState
from src.tools.archivist_tools import track_power_strain, update_relationship

async def validate_phase_3():
    print("\n--- PHASE 3 VALIDATION ---")

    # Initialize a dummy state
    state = FableAgentState(
        current_timeline_date="2026-05-06",
        power_debt=PowerDebt(strain_level=20),
        active_characters={
            "Mayumi": CharacterState(trust_level=10, disposition="curious")
        }
    )

    print("\n[1/2] Validating ADK Tool: track_power_strain...")
    # Simulate the LLM calling the tool
    result_1 = await track_power_strain(state, power_used="Material Burst", strain_increase=70)
    print(f"  -> Result: {result_1}")
    print(f"  -> State mutated: strain_level is now {state.power_debt.strain_level}")
    assert state.power_debt.strain_level == 90

    print("\n[2/2] Validating ADK Tool: update_relationship...")
    # Simulate the LLM calling the tool
    result_2 = await update_relationship(
        state, 
        target_name="Mayumi", 
        trust_delta=-30, 
        disposition="wary", 
        dynamic_tags=["suspicious"]
    )
    print(f"  -> Result: {result_2}")
    print(f"  -> State mutated: trust_level is now {state.active_characters['Mayumi'].trust_level}")
    print(f"  -> State mutated: disposition is now {state.active_characters['Mayumi'].disposition}")
    assert state.active_characters["Mayumi"].trust_level == -20

    print("\n--- VALIDATION COMPLETE ---")

if __name__ == "__main__":
    asyncio.run(validate_phase_3())
