from google.adk.workflow import FunctionNode, JoinNode, START, Workflow
# build_node has no public alternative; not exported in google.adk.workflow.__all__.
from google.adk.workflow.utils._workflow_graph_utils import build_node  # noqa: I001 — no public alternative

from src.state.models import FableAgentState

from src.nodes.storyteller import create_storyteller_node
from src.nodes.archivist import create_archivist_node
from src.nodes.auditor import run_auditor
from src.nodes.world_builder import run_world_builder
from src.nodes.recovery import run_recovery

from src.nodes.init_research import create_query_planner, create_lore_hunter, parse_queries
from src.nodes.lore_keeper import create_lore_keeper, inject_lore_to_state, create_fallback_extractor, fallback_injector

# Phase 9: Narrative Intelligence Nodes
from src.nodes.intent_router import run_intent_router
from src.nodes.summarizer import summarizer_node


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

    # Fallback nodes
    fallback_extractor_agent = create_fallback_extractor()
    fallback_extractor_node = build_node(fallback_extractor_agent)
    fallback_injector_node = fallback_injector

    # Phase 9 Nodes
    intent_router_node = run_intent_router

    # Phase H follow-up: the summarizer was previously LlmAgent + parser-@node.
    # Now summarizer_node does the LLM call directly (see src/nodes/summarizer.py),
    # so the shim agent is gone. archivist_node -> summarizer_node directly.
    summarizer_parser_node = summarizer_node

    # Phase B (Option A): user_choice_input removed entirely. The
    # workflow terminates after summarizer; the WS runner emits a
    # chapter_meta frame carrying state.last_chapter_meta. The frontend
    # renders the picker WITHOUT a HITL pause. Each user choice triggers
    # a fresh runner.run_async(new_message=Content(...), state_delta={...})
    # which gets a NEW invocation_id -- so per-chapter rewind/rewrite
    # finally works.

    # 3. Define the Graph Edges (State Machine Logic)

    edges = [
        # Boot Phase (HITL)
        (START, world_builder_node),

        # WorldBuilder routes:
        #   setup -> query_planner (first run; runs lore_dump+wizard+config+research swarm)
        #   skip  -> intent_router (subsequent chapters; world is already built)
        # The skip route is what makes Option A work: each chapter starts
        # with a fresh invocation_id at run_async time, world_builder
        # detects post-setup state and short-circuits to the turn loop.
        (world_builder_node, {
            "setup": query_planner_node,
            "skip": intent_router_node,
        }),

        # Parse the JSON response into a Python List
        (query_planner_node, query_parser_node),

        # The list is passed to the Parallel Worker, which fans out
        (query_parser_node, lore_hunter_swarm),

        # The parallel tasks feed into the Join node
        (lore_hunter_swarm, swarm_join),

        # The Join node hands the aggregated list to the Keeper
        (swarm_join, lore_keeper_node),

        # Keeper evaluates state
        (lore_keeper_node, lore_keeper_injector),

        # Fallback routing if keeper hallucinated
        (lore_keeper_injector, {
            "fallback": fallback_extractor_node,
            "success": intent_router_node
        }),

        (fallback_extractor_node, fallback_injector_node),
        (fallback_injector_node, {
            "success": intent_router_node
        }),

        # Intent Router decides: continue story OR branch to research swarm
        (intent_router_node, {
            "story": storyteller_node,
            "research": query_planner_node
        }),

        # Core Story Loop
        (storyteller_node, auditor_node),
        # Auditor routes:
        #   passed   -> archivist (success path; resets retry counter)
        #   failed   -> storyteller (retry; counter is bumped in auditor)
        #   recovery -> recovery_node (after 3 consecutive failures)
        (auditor_node, {
            "passed": archivist_node,
            "failed": storyteller_node,
            "recovery": recovery_node
        }),

        # Recovery: writes a fallback prose into state.last_story_text
        # and terminates. Frontend will render generic fallback choices
        # from runner's chapter_meta frame (synthesised when
        # state.last_chapter_meta is missing).
        # (recovery_node has no outgoing edge -> terminal)

        # Narrative Intelligence: Summarize, then TERMINATE.
        # No HITL, no loop-back. The runner emits chapter_meta after the
        # workflow exits; the next user choice triggers a fresh
        # run_async with state_delta carrying last_user_choice.
        (archivist_node, summarizer_parser_node),
        # summarizer_parser_node has no outgoing edge -> terminal
    ]

    # 4. Create the Workflow Node.
    # Nodes are inferred from edges by WorkflowGraph.model_post_init — do
    # NOT pass nodes/sub_nodes explicitly. recovery_node is reachable via
    # the auditor's "recovery" route above.
    fable_graph = Workflow(
        name="fable_main_workflow",
        edges=edges,
        state_schema=FableAgentState,
    )

    return fable_graph
