from google.adk.workflow import Workflow
from google.adk.workflow.utils._workflow_graph_utils import build_node
from google.adk.workflow._function_node import FunctionNode

from src.nodes.storyteller import create_storyteller_node
from src.nodes.archivist import create_archivist_node
from src.nodes.auditor import run_auditor
from src.nodes.world_builder import run_world_builder
from src.nodes.recovery import run_recovery

def build_fable_workflow() -> Workflow:
    """
    Constructs the ADK 2.0 deterministic Graph-Based Workflow.
    This replaces the manual `run_pipeline` loop from V1.
    """
    
    # 1. Instantiate Nodes (ADK agents must be wrapped using build_node for graph integration)
    storyteller_agent = create_storyteller_node()
    archivist_agent = create_archivist_node()
    
    storyteller_node = build_node(storyteller_agent)
    archivist_node = build_node(archivist_agent)
    
    # The auditor is a @node decorated function, so it's already a BaseNode instance
    auditor_node = run_auditor
    
    # The world_builder is also a @node decorated function
    world_builder_node = run_world_builder
    
    # Create the recovery node manually as an example
    recovery_node = FunctionNode(func=run_recovery, name="recovery")
    
    # 2. Define the Graph Edges (State Machine Logic)
    
    edges = [
        # Chain from START to world_builder for setup
        ("START", world_builder_node),
        
        # After setup, go to storyteller
        (world_builder_node, storyteller_node),
        
        # Chain from storyteller to auditor
        (storyteller_node, auditor_node),
        
        # Auditor Conditional Routing using a RoutingMap dict
        (auditor_node, {
            "passed": archivist_node,
            "failed": storyteller_node
        })
    ]
    
    # 3. Create the Workflow Node
    fable_graph = Workflow(
        name="fable_main_workflow",
        sub_nodes=[
            world_builder_node,
            storyteller_node,
            auditor_node,
            archivist_node,
            recovery_node
        ],
        edges=edges
    )
    
    return fable_graph
