import asyncio
import os
import sys

# Ensure project root is in path for imports
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from src.state.models import FableAgentState, CharacterState
from src.services.session_manager import create_fable_session, session_service

async def validate_phase_1():
    print("--- PHASE 1 VALIDATION ---")
    
    # 1. Test State Model
    print("\n[1/3] Validating Pydantic AgentState...")
    try:
        initial_state = FableAgentState(
            current_timeline_date="2026-05-06",
            current_location_node="first_high_hallway",
            active_characters={
                "Tatsuya Shiba": CharacterState(trust_level=50, disposition="calculating", is_present=True)
            }
        )
        print(f"✓ State Model parsed successfully: {initial_state.current_location_node}")
    except Exception as e:
        print(f"✗ State Model validation failed: {e}")
        return

    # 2. Test Session Creation
    print("\n[2/3] Validating Session Creation...")
    try:
        user_id = "test_user_pro"
        session_id = await create_fable_session(user_id=user_id)
        print(f"✓ Session created successfully: {session_id}")
    except Exception as e:
        print(f"✗ Session creation failed: {e}")
        print("Note: Ensure Postgres is running and DATABASE_URL is correct.")
        # We don't return here so we can see other errors
    
    # 3. Test Native Branching
    print("\n[3/3] Validating Zero-Logic Branching...")
    try:
        branch_id = await create_fable_session(user_id=user_id, parent_session_id=session_id)
        print(f"✓ Branch created successfully with parent: {branch_id}")
    except Exception as e:
        print(f"✗ Branching failed: {e}")

    print("\n--- VALIDATION COMPLETE ---")

if __name__ == "__main__":
    asyncio.run(validate_phase_1())
