from google.adk.workflow import Workflow
from google.adk.workflow._graph_definitions import Edge

from src.nodes.storyteller import create_storyteller_node
from src.nodes.archivist import create_archivist_node
from src.nodes.auditor import run_auditor

def build_fable_workflow() -> Workflow:
    """
    Constructs the ADK 2.0 deterministic Graph-Based Workflow.
    This replaces the manual `run_pipeline` loop from V1.
    """
    
    # 1. Instantiate Nodes
    storyteller_node = create_storyteller_node()
    archivist_node = create_archivist_node()
    # The auditor is a @node decorated function, so it's already a BaseNode instance
    auditor_node = run_auditor
    
    # 2. Define the Graph Edges (State Machine Logic)
    # ADK 2.0 supports tuple-based chains or RoutingMaps.
    # The first element in the list is automatically considered the entry point
    # if it's connected to 'START' via tuple, or we can just specify the chain.
    
    edges = [
        # Chain from START to storyteller
        ("START", storyteller_node),
        
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
            storyteller_node,
            auditor_node,
            archivist_node
        ],
        edges=edges
    )
    
    return fable_graph
