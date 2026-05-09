from google.adk.apps.app import App
from google.adk.plugins.logging_plugin import LoggingPlugin
from google.adk.runners import Runner

from src.graph.workflow import build_fable_workflow
from src.plugins.global_instruction import (
    GlobalInstructionPlugin,
    storyteller_instruction_provider,
)
# Suspicion plugin disabled post-refactor: it filtered on agent_name ==
# 'choice_generator' (a node that no longer exists; choices now come
# from the storyteller's chapter_meta). The plugin's tier vocabulary
# (oblivious/uneasy/suspicious/breakthrough) also doesn't match the
# new ChoiceTier (canon/divergence/character/wildcard). Re-introducing
# requires both a filter update AND a tier-vocabulary alignment; track
# as a separate feature rather than a refactor revival.
# from src.plugins.suspicion_plugin import SuspicionPlugin
from src.plugins.telemetry import TelemetryPlugin
from src.services.memory_service import memory_service
from src.services.session_manager import session_service

# 1. Build the ADK 2.0 Graph Workflow
fable_main_workflow = build_fable_workflow()

# 2. Define the ADK 2.0 Application Container
fable_app = App(
    name="fable_2_0",
    root_agent=fable_main_workflow,  # ADK 2.0 Beta: root_agent accepts BaseNode
    plugins=[
        # Native global-instruction plugin driven by our dynamic provider.
        # The provider filters to the storyteller agent and reads ctx.state
        # to produce strain/mood/anti-worf notes per turn.
        GlobalInstructionPlugin(
            global_instruction=storyteller_instruction_provider,
            name="fable_global_instruction",
        ),
        TelemetryPlugin(),
        # SuspicionPlugin() removed post-refactor (see import-block comment
        # above). Re-add when the plugin is updated for the new
        # ChoiceTier vocabulary and storyteller-as-choice-emitter flow.
        # Bundled logging — replaces the raw-token-logging duplication
        # previously baked into TelemetryPlugin.
        LoggingPlugin(name="fable_logging"),
    ],
    # ADK auto-compaction (EventsCompactionConfig) is intentionally OFF.
    # Reason: with Option A (per-chapter invocation_ids), each chapter is
    # its own bounded run_async invocation; cross-chapter continuity is
    # handled by the storyteller's PRIOR CHAPTER CONTEXT block + the
    # LoreEmbedding chapter_summary::N recall path. Auto-compaction adds
    # no value here AND triggers a known race in
    # google/adk/apps/compaction.py: the compaction step calls
    # session_service.append_event(session=...) using a session reference
    # whose _storage_update_marker has gone stale after the 100+ tool-call
    # events the archivist appended during the same turn -- raising
    # 'The session has been modified in storage since it was loaded'.
    # Within-chapter context bloat is bounded by gemini-3.1-flash-lite's
    # native context window; archivist tool counts are also capped by
    # mode='AUTO' + the explicit "NEVER call same tool with same args
    # twice" rule in its instruction.
)

# 3. Initialize the Runner
# The Runner bridges the declarative App with the stateful Services.
# We explicitly inject our Local Postgres/Ollama memory and session services here.
fable_runner = Runner(
    app=fable_app,
    session_service=session_service,
    memory_service=memory_service,
)
