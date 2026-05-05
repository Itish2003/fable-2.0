import asyncio
import os
import sys

# Ensure project root is in path for imports
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from src.graph.workflow import build_fable_workflow
from google.adk.workflow._workflow_graph import WorkflowGraph

async def validate_phase_4():
    print("\n--- PHASE 4 VALIDATION ---")

    print("\n[1/2] Building Fable Graph Workflow...")
    try:
        fable_workflow = build_fable_workflow()
        print(f"✓ Workflow created: {fable_workflow.name}")
    except Exception as e:
        print(f"✗ Workflow creation failed: {e}")
        return

    print("\n[2/2] Validating Graph Edges and Logic...")
    try:
        # Convert edges to WorkflowGraph to trigger ADK's native graph validation
        graph = WorkflowGraph.from_edge_items(fable_workflow.edges)
        graph.validate_graph()
        print("✓ Graph routing logic is valid and deterministic.")
        
        # Test Auditor Node isolated logic
        from src.nodes.auditor import run_auditor
        from unittest.mock import MagicMock
        from src.state.models import FableAgentState
        
        ctx = MagicMock()
        mock_inv_ctx = MagicMock()
        
        test_state = FableAgentState(
            forbidden_concepts=["Taurus Silver"],
            anti_worf_rules={"Miyuki": "Cannot be defeated easily."}
        )
        mock_inv_ctx.agent_states = {"auditor": test_state}
        ctx.get_invocation_context.return_value = mock_inv_ctx
        
        # Test Pass (Since run_auditor is decorated with @node, we call the underlying func directly for testing)
        print("\n  -> Testing Auditor Pass...")
        # ADK 2.0 @node decorator wraps the function in a BaseNode. 
        # We can extract the original async function via the internal attribute if needed, 
        # or we can test the logic directly if we just mock the function call.
        # For simplicity in this validation script, we'll import the logic directly.
        from src.nodes.auditor import run_auditor
        
        # Access the wrapped function (ADK 2.0 uses _func for FunctionNode wrappers)
        underlying_func = run_auditor._func
        
        result_pass = await underlying_func(ctx=ctx, node_input="Tatsuya drank tea.")
        print(f"     Result: {result_pass}")
        assert result_pass == "passed"
        
        # Test Fail (Epistemic Leak)
        print("  -> Testing Auditor Fail (Epistemic)...")
        result_fail = await underlying_func(ctx=ctx, node_input="Tatsuya is secretly Taurus Silver.")
        print(f"     Result: {result_fail}")
        assert result_fail == "failed"
        
        print("\n✓ Auditor logic successfully triggers conditional edges.")

    except Exception as e:
        print(f"✗ Graph validation failed: {e}")

    print("\n--- VALIDATION COMPLETE ---")

if __name__ == "__main__":
    asyncio.run(validate_phase_4())
