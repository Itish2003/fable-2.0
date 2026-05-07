<div align="center">
  <h1>🌌 Fable 2.0 Engine</h1>
  <p><strong>A deterministic, event-sourced, simulation-grade interactive fiction engine.</strong></p>
</div>

---

Fable 2.0 is a complete architectural paradigm shift from traditional "prompt-chained" AI Dungeon Masters. Built entirely on the **Google ADK 2.0 Beta** framework, it abandons fragile `while` loops and monolithic prompts in favor of a strictly typed Directed Acyclic Graph (DAG), native map-reduce research swarms, and an event-sourced timeline.

It acts as an uncompromising AI Game Master, utilizing a multi-agent tool-calling loop, a local GraphRAG memory system, and an interactive state machine to simulate living narrative worlds.

## 🚀 Key Features

*   **Deterministic Orchestration:** Control flow is managed by the ADK `Workflow` Graph. The `Storyteller` writes prose, the `Auditor` checks it against canon rules, and the `Archivist` mutates the persistent state using tools. If an LLM hallucinates, the graph catches the failure and explicitly routes backward to regenerate.
*   **Event-Sourced Timelines:** The database doesn't just hold the "current" state; it holds an immutable ledger of every event. If you click **"Undo"**, the native ADK `rewind_async()` API flawlessly reconstructs the timeline backward to the exact millisecond before the mistake.
*   **Parallel Research Swarm:** Fable 2.0 can handle wild crossover fanfiction out-of-the-box. Inputting a prompt dynamically spawns a parallel swarm of `LoreHunter` agents (via ADK's `parallel_worker=True`) that execute Google Searches and scrape wikis simultaneously, synthesizing the rules of the crossover into a rigid "World Bible" before Chapter 1 begins.
*   **Semantic Suspicion Engine:** Using local Ollama `pgvector` embeddings, the engine calculates real-time cosine similarity between the generated prose and hidden "forbidden concepts." If the protagonist brushes up against a secret, the engine mathematically detects the subtext and dynamically shifts the interactive UI into a 4-tier "Awareness Spectrum."
*   **Dynamic Prompt Assembly:** Replaces "Super Prompts." Micro-agents receive highly targeted instructions via ADK Plugins only when necessary (e.g., injecting an aggressive "Anti-Nerf" prompt if the protagonist operates on a continental scale). See [PROMPTING_STRATEGY.md](docs/PROMPTING_STRATEGY.md).

---

## 🏗️ Tech Stack

*   **Framework:** Google ADK 2.0 Beta (`google.adk`)
*   **LLM Backend:** Gemini 3.1 Flash Lite Preview (via Google GenAI SDK)
*   **Memory / Retrieval:** PostgreSQL (`pgvector`) + Local Ollama (`nomic-embed-text:v1.5`)
*   **API Server:** FastAPI + WebSockets
*   **Frontend:** React, Vite, TailwindCSS v4, Framer Motion

---

## 🛠️ Local Setup Instructions

### 1. Prerequisites
- **Python 3.12+**
- **Node.js 20+**
- **Ollama** (Running locally with `nomic-embed-text:v1.5`)
- **PostgreSQL** (with `pgvector` extension enabled)
- `uv` (Fast Python package installer)

### 2. Environment Configuration
Clone the repository and create an environment file at the root:
```bash
echo "GEMINI_API_KEY=your_google_ai_studio_key" > .env
```

### 3. Database Initialization
Ensure your local PostgreSQL server is running, then create the database and extension:
```bash
psql -U postgres -c "CREATE DATABASE fable2_0;"
psql -U postgres -d fable2_0 -c "CREATE EXTENSION IF NOT EXISTS vector;"
```
Install Python dependencies via `uv` and initialize the schema:
```bash
uv sync
PYTHONPATH=. uv run python src/database.py
```

---

## 🎮 Running the Simulation

To fully experience the Fable 2.0 narrative simulation, you must boot both the ADK engine server and the React frontend.

### Terminal 1: The Engine (Backend)
```bash
PYTHONPATH=. uv run uvicorn src.main:app --host 127.0.0.1 --port 8001
```

### Terminal 2: The Interface (Frontend)
```bash
cd frontend
npm install
npm run dev
```

Navigate to **http://localhost:5173** in your browser. The system will automatically establish a secure WebSocket connection to the ADK `Runner` and trigger the multi-turn, interactive World Builder setup sequence.