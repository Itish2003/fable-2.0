from google.adk.apps.app import App
from google.adk.runners import Runner

from src.graph.workflow import build_fable_workflow
from src.services.session_manager import session_service
from src.services.memory_service import memory_service
from src.plugins.global_instruction import GlobalInstructionPlugin

# 1. Build the ADK 2.0 Graph Workflow
fable_main_workflow = build_fable_workflow()

# 2. Define the ADK 2.0 Application Container
fable_app = App(
    name="fable_2_0",
    root_agent=fable_main_workflow,  # ADK 2.0 Beta quirk: root_agent accepts Workflow/BaseNode
    plugins=[
        GlobalInstructionPlugin()
    ]
)

# 3. Initialize the Runner
# The Runner bridges the declarative App with the stateful Services.
# We explicitly inject our Local Postgres/Ollama memory and session services here.
fable_runner = Runner(
    app=fable_app,
    session_service=session_service,
    memory_service=memory_service,
)
