# Fable 2.0 Engine

Fable 2.0 is a deterministic, graph-based narrative simulation engine built on the **Google ADK 2.0 Beta**. It acts as a highly constrained AI Dungeon Master, utilizing an uncompromising LLM tool-calling loop, a local GraphRAG memory system, and an interactive state machine to simulate living narrative worlds.

## Core Architecture

The backend architecture consists of several decoupled layers, allowing for precise control over narrative generation and state integrity.

### 1. The Workflow Graph
Unlike V1's dynamic `while` loops, Fable 2.0 routes control flow through a strict, deterministic Directed Acyclic Graph (DAG) built with `google.adk.workflow.Workflow`.
*   **WorldBuilderNode**: Uses ADK's `RequestInput` to execute a multi-turn, Human-in-the-Loop (HITL) setup wizard to bootstrap the universe and protagonist.
*   **StorytellerNode**: A `gemini-3.1-flash-lite-preview` LLM Agent strictly isolated to prose generation.
*   **AuditorNode**: A pure Python Function Node that evaluates the Storyteller's output against dynamic integrity constraints (Epistemic Boundaries and Anti-Worf rules). If the prose violates rules, it routes backward to rewrite it.
*   **ArchivistNode**: A `PlanReAct` LLM Agent that *never* generates prose. It exclusively invokes tools (`record_divergence`, `advance_timeline`, `track_power_strain`) to mutate the Pydantic State and World Bible.

### 2. Stateful Memory & Session Management
*   **FableAgentState**: A highly structured `pydantic` state representation that holds the "Hot State" (current timeline date, protagonist power strain, character trust levels, active scene variables).
*   **GraphRAG Engine**: Built locally using Postgres (`pgvector`) and Ollama (`nomic-embed-text:v1.5`). Implements Epistemic Filtering so characters can only retrieve information they canonically "know."

### 3. Server Integration
*   The system runs on **FastAPI**.
*   Real-time execution is handled via **WebSockets**. The ADK 2.0 `runner.run_async()` generator is consumed by the server, filtering internal ADK Event objects to stream narrative text, tool execution statuses, and `RequestInput` pauses to the frontend UI.

## Getting Started

1. **Install Dependencies:**
   ```bash
   uv sync
   uv pip install fastapi uvicorn
   ```

2. **Database Setup:**
   Ensure you have a local PostgreSQL instance running. 
   ```bash
   psql -U postgres -c "CREATE DATABASE fable2_0;"
   psql -U postgres -d fable2_0 -c "CREATE EXTENSION IF NOT EXISTS vector;"
   ```
   Then initialize the schema:
   ```bash
   PYTHONPATH=. .venv/bin/python src/database.py
   ```

3. **Start the Local Engine:**
   ```bash
   uvicorn src.main:app --host 127.0.0.1 --port 8001 --reload
   ```

## Running the System

To fully experience the narrative simulation, you must start both the ADK 2.0 Engine and the React UI.

### 1. Start the Backend (ADK 2.0 Engine)
The backend is a FastAPI application that drives the ADK state machine.
*   **Location:** Project Root (`/Users/itish/Downloads/fable2.0`)
*   **Port:** 8001
*   **Command:**
    ```bash
    PYTHONPATH=. .venv/bin/uvicorn src.main:app --host 127.0.0.1 --port 8001 --reload
    ```

### 2. Start the Frontend (React UI)
The frontend is a Vite-based React app that connects to the engine via WebSockets.
*   **Location:** `/Users/itish/Downloads/fable2.0/frontend`
*   **Port:** 5174 (default Vite port)
*   **Command:**
    ```bash
    cd frontend
    npm run dev
    ```

Once both are running, open your browser to **http://localhost:5174**. The UI will automatically create a session and trigger the initial **World Builder** setup wizard.

## Development Phases
This project was strictly implemented across 7 phases:
1. `PHASE_1_STATE_MODEL`: Pydantic Models & Session Manager
2. `PHASE_2_GRAPHRAG`: Postgres, pgvector & Local Ollama Embeddings
3. `PHASE_3_NODE_CONFIG`: Agent wrapping & strict Tool execution
4. `PHASE_4_ORCHESTRATION`: The DAG State Machine
5. `PHASE_5_WORLD_BOOT`: Interactive `RequestInput` World Building
6. `PHASE_6_SERVER_INTEGRATION`: FastAPI & WebSocket Runner Loop
7. `PHASE_7_PRODUCTIONIZATION`: Telemetry, Context Compaction & Error Recovery
