# Fable 2.0 / ADK 2.0 Project Instructions

- **Dependency Management**: This project uses `uv` for dependency management instead of `pip`. The virtual environment is located at `.venv`. Always use `uv pip` to install new dependencies.
- **ADK 2.0 Mapping**: The ADK 2.0 source code (`.venv/lib/python3.12/site-packages/google/adk`) has been mapped using the `code-review-graph` tool. 
  - The tool is installed in the local `.venv`.
  - The SQLite graph database is located in the ADK package directory.
  - An HTML visualization of the ADK 2.0 architecture is available at `adk-2.0-map.html` in the root of the project.
- **Agent Workflow Optimization**: When asked to build or debug ADK 2.0 agents, use the local `code-review-graph` CLI tools (e.g., `.venv/bin/code-review-graph`) to query the framework's architecture, dependencies, and call chains to minimize token consumption and improve accuracy.