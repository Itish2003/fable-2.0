from google.adk.apps.app import App
from google.adk.apps.compaction import EventsCompactionConfig
from google.adk.apps.llm_event_summarizer import LlmEventSummarizer
from google.adk.models.google_llm import Gemini
from google.adk.plugins.logging_plugin import LoggingPlugin
from google.adk.runners import Runner

from src.graph.workflow import build_fable_workflow
from src.plugins.global_instruction import (
    GlobalInstructionPlugin,
    storyteller_instruction_provider,
)
from src.plugins.suspicion_plugin import SuspicionPlugin
from src.plugins.telemetry import TelemetryPlugin
from src.services.memory_service import memory_service
from src.services.session_manager import session_service

# Same lightweight model the archivist/summarizer nodes use — keeps
# compaction summaries fast and consistent with the rest of the graph.
COMPACTION_MODEL = "gemini-3.1-flash-lite-preview"

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
        SuspicionPlugin(),
        # Bundled logging — replaces the raw-token-logging duplication
        # previously baked into TelemetryPlugin.
        LoggingPlugin(name="fable_logging"),
    ],
    events_compaction_config=EventsCompactionConfig(
        # Sliding-window compaction.
        compaction_interval=20,
        overlap_size=3,
        # Token-threshold compaction.
        token_threshold=15000,
        event_retention_size=5,
        # Explicit summarizer — required because root_agent is a Workflow,
        # not an LlmAgent, so ADK's lazy default cannot resolve a model.
        summarizer=LlmEventSummarizer(llm=Gemini(model=COMPACTION_MODEL)),
    ),
)

# 3. Initialize the Runner
# The Runner bridges the declarative App with the stateful Services.
# We explicitly inject our Local Postgres/Ollama memory and session services here.
fable_runner = Runner(
    app=fable_app,
    session_service=session_service,
    memory_service=memory_service,
)
