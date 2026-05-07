from google.adk.apps.app import App
from google.adk.apps.compaction import EventsCompactionConfig
from google.adk.runners import Runner

from src.graph.workflow import build_fable_workflow
from src.services.session_manager import session_service
from src.services.memory_service import memory_service
from src.plugins.global_instruction import GlobalInstructionPlugin
from src.plugins.telemetry import TelemetryPlugin
from src.plugins.suspicion_plugin import SuspicionPlugin

# 1. Build the ADK 2.0 Graph Workflow
fable_main_workflow = build_fable_workflow()

# 2. Define the ADK 2.0 Application Container
fable_app = App(
    name="fable_2_0",
    root_agent=fable_main_workflow,  # ADK 2.0 Beta quirk: root_agent accepts Workflow/BaseNode
    plugins=[
        GlobalInstructionPlugin(),
        TelemetryPlugin(),
        SuspicionPlugin()
    ],
    events_compaction_config=EventsCompactionConfig(
        # In a real app, this limits how many raw events to keep before summarizing
        compaction_interval=20, 
        overlap_size=3,
        token_threshold=15000, # Trigger summary early if context overflows
        event_retention_size=5, # Number of events to keep raw after compaction
        # In ADK Beta, summarizer defaults to a built-in LLM summarizer if omitted
    )
)

# 3. Initialize the Runner
# The Runner bridges the declarative App with the stateful Services.
# We explicitly inject our Local Postgres/Ollama memory and session services here.
fable_runner = Runner(
    app=fable_app,
    session_service=session_service,
    memory_service=memory_service,
)
