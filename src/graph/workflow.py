from google.adk.workflow import Workflow
from google.adk.workflow.utils._workflow_graph_utils import build_node
from google.adk.workflow._function_node import FunctionNode
from google.adk.workflow._join_node import JoinNode

from src.nodes.storyteller import create_storyteller_node
from src.nodes.archivist import create_archivist_node
from src.nodes.auditor import run_auditor
from src.nodes.world_builder import run_world_builder
from src.nodes.recovery import run_recovery

from src.nodes.init_research import create_query_planner, create_lore_hunter, parse_queries
from src.nodes.lore_keeper import create_lore_keeper, inject_lore_to_state

def build_fable_workflow() -> Workflow:
    """
    Constructs the ADK 2.0 deterministic Graph-Based Workflow.
    This replaces the manual `run_pipeline` loop from V1.
    """
    
    # 1. Existing Nodes
    storyteller_agent = create_storyteller_node()
    archivist_agent = create_archivist_node()
    
    storyteller_node = build_node(storyteller_agent)
    archivist_node = build_node(archivist_agent)
    
    auditor_node = run_auditor
    world_builder_node = run_world_builder
    recovery_node = FunctionNode(func=run_recovery, name="recovery")
    
    # 2. New Phase 8 Swarm Nodes
    query_planner_agent = create_query_planner()
    lore_hunter_agent = create_lore_hunter()
    lore_keeper_agent = create_lore_keeper()
    
    query_planner_node = build_node(query_planner_agent)
    query_parser_node = parse_queries
    
    # CRITICAL: Configure the agent for parallel fan-out
    lore_hunter_agent.parallel_worker = True
    lore_hunter_swarm = build_node(lore_hunter_agent)
    
    # The JoinNode automatically waits for all instances of the swarm to finish
    # and aggregates their outputs into a list for the Lore Keeper
    swarm_join = JoinNode(name="swarm_join")
    
    lore_keeper_node = build_node(lore_keeper_agent)
    lore_keeper_injector = inject_lore_to_state
    
    # 3. Define the Graph Edges (State Machine Logic)
    
    edges = [
        # Boot Phase (HITL)
        ("START", world_builder_node),
        
        # After WorldBuilder completes, trigger the Query Planner
        (world_builder_node, query_planner_node),
        
        # Parse the JSON response into a Python List
        (query_planner_node, query_parser_node),
        
        # The list is passed to the Parallel Worker, which fans out
        (query_parser_node, lore_hunter_swarm),
        
        # The parallel tasks feed into the Join node
        (lore_hunter_swarm, swarm_join),
        
        # The Join node hands the aggregated list to the Keeper
        (swarm_join, lore_keeper_node),
        
        # Keeper writes to state
        (lore_keeper_node, lore_keeper_injector),
        
        # Finally, with the State fully populated, we enter the main story loop
        (lore_keeper_injector, storyteller_node),
        
        # Core Story Loop
        (storyteller_node, auditor_node),
        (auditor_node, {
            "passed": archivist_node,
            "failed": storyteller_node
        })
    ]
    
    # 4. Create the Workflow Node
    fable_graph = Workflow(
        name="fable_main_workflow",
        sub_nodes=[
            world_builder_node,
            query_planner_node,
            query_parser_node,
            lore_hunter_swarm,
            swarm_join,
            lore_keeper_node,
            lore_keeper_injector,
            storyteller_node,
            auditor_node,
            archivist_node,
            recovery_node
        ],
        edges=edges
    )
    
    return fable_graph
