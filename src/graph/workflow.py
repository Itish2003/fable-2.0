from google.adk.workflow import FunctionNode, JoinNode, START, Workflow
# build_node has no public alternative; not exported in google.adk.workflow.__all__.
from google.adk.workflow.utils._workflow_graph_utils import build_node  # noqa: I001 — no public alternative

from src.state.models import FableAgentState

from src.nodes.storyteller import create_storyteller_node
from src.nodes.archivist import create_archivist_node
from src.nodes.summarizer import create_summarizer_node
from src.nodes.auditor import run_auditor
from src.nodes.world_builder import run_world_builder
from src.nodes.recovery import run_recovery

from src.nodes.init_research import create_query_planner, create_lore_hunter, parse_queries
from src.nodes.lore_keeper import (
    create_lore_keeper,
    inject_lore_to_state,
    create_fallback_extractor,
    fallback_injector,
)

# Phase 9: Narrative Intelligence Nodes
from src.nodes.intent_router import run_intent_router

# Idiomatic-ADK refactor: declarative LlmAgents with output_schema +
# downstream FunctionNode merge nodes. The merge nodes apply the parsed
# schema artifacts to canonical state fields deterministically.
from src.nodes.storyteller_merge import storyteller_merge
from src.nodes.archivist_merge import archivist_merge
from src.nodes.summarizer_persist import summarizer_persist


def build_fable_workflow() -> Workflow:
    """
    Constructs the ADK 2.0 deterministic Graph-Based Workflow.

    Chapter generation pipeline (post-refactor):

        intent_router
          → storyteller          [LlmAgent + output_schema=StorytellerOutput]
          → storyteller_merge    [FunctionNode: prepend # Chapter N header]
          → auditor              [FunctionNode: structural + content audits]
              ↓ "passed"
              → archivist        [LlmAgent + output_schema=ArchivistDelta]
              → archivist_merge  [FunctionNode: apply delta to canonical state]
              → summarizer       [LlmAgent + output_schema=ChapterSummaryOutput]
              → summarizer_persist [FunctionNode: append summary, embed]
              ↓ "failed"
              → storyteller     [retry, up to 3]
              ↓ "recovery"
              → recovery_node   TERMINAL

    Three LLM calls per chapter (storyteller, archivist, summarizer);
    three FunctionNode merges that are pure deterministic state writes.
    No tool loops, no exit conditions, no parsers.
    """

    # 1. Story-loop nodes (declarative LlmAgents + their merge passes).
    storyteller_agent = create_storyteller_node()
    archivist_agent = create_archivist_node()
    summarizer_agent = create_summarizer_node()

    storyteller_node = build_node(storyteller_agent)
    archivist_node = build_node(archivist_agent)
    summarizer_node = build_node(summarizer_agent)

    storyteller_merge_node = storyteller_merge
    archivist_merge_node = archivist_merge
    summarizer_persist_node = summarizer_persist

    auditor_node = run_auditor
    world_builder_node = run_world_builder
    recovery_node = FunctionNode(func=run_recovery, name="recovery")

    # 2. Phase 8 Swarm Nodes (lore-init pipeline; unchanged).
    query_planner_agent = create_query_planner()
    lore_hunter_agent = create_lore_hunter()
    lore_keeper_agent = create_lore_keeper()

    query_planner_node = build_node(query_planner_agent)
    query_parser_node = parse_queries

    lore_hunter_agent.parallel_worker = True
    lore_hunter_swarm = build_node(lore_hunter_agent)

    swarm_join = JoinNode(name="swarm_join")

    lore_keeper_node = build_node(lore_keeper_agent)
    lore_keeper_injector = inject_lore_to_state

    fallback_extractor_agent = create_fallback_extractor()
    fallback_extractor_node = build_node(fallback_extractor_agent)
    fallback_injector_node = fallback_injector

    # Phase 9: per-turn router.
    intent_router_node = run_intent_router

    # 3. Edges — the state machine.
    edges = [
        # Boot (HITL via world_builder).
        (START, world_builder_node),

        # WorldBuilder routes:
        #   setup -> query_planner (first run; runs lore_dump+wizard+config+research swarm)
        #   skip  -> intent_router (subsequent chapters; world already built)
        (world_builder_node, {
            "setup": query_planner_node,
            "skip": intent_router_node,
        }),

        # Setup pipeline (unchanged).
        (query_planner_node, query_parser_node),
        (query_parser_node, lore_hunter_swarm),
        (lore_hunter_swarm, swarm_join),
        (swarm_join, lore_keeper_node),
        (lore_keeper_node, lore_keeper_injector),
        (lore_keeper_injector, {
            "fallback": fallback_extractor_node,
            "success": intent_router_node,
        }),
        (fallback_extractor_node, fallback_injector_node),
        (fallback_injector_node, {
            "success": intent_router_node,
        }),

        # Per-turn intent routing.
        (intent_router_node, {
            "story": storyteller_node,
            "research": query_planner_node,
        }),

        # ─────────────────── chapter generation ─────────────────
        # Storyteller emits StorytellerOutput (prose + chapter_meta) into
        # state.storyteller_output via output_key. storyteller_merge
        # prepends the deterministic "# Chapter N" header from
        # state.chapter_count and writes last_story_text +
        # last_chapter_meta. Auditor validates structurally + content.
        (storyteller_node, storyteller_merge_node),
        (storyteller_merge_node, auditor_node),
        (auditor_node, {
            "passed": archivist_node,
            "failed": storyteller_node,
            "recovery": recovery_node,
        }),

        # Archivist emits ArchivistDelta into state.archivist_delta;
        # archivist_merge applies it deterministically. Then summarizer
        # emits ChapterSummaryOutput into state.summary_output;
        # summarizer_persist appends to state.chapter_summaries and
        # writes the chapter_summary::<N> LoreEmbedding.
        (archivist_node, archivist_merge_node),
        (archivist_merge_node, summarizer_node),
        (summarizer_node, summarizer_persist_node),
        # summarizer_persist_node is TERMINAL.
        # recovery_node is TERMINAL.
    ]

    fable_graph = Workflow(
        name="fable_main_workflow",
        edges=edges,
        state_schema=FableAgentState,
    )

    return fable_graph
