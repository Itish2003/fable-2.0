<div align="center">
  <h1>🌌 Fable 2.0 Engine</h1>
  <p><strong>A deterministic, event-sourced, simulation-grade interactive fiction engine.</strong></p>
</div>

---

> **v2.1 (May 2026)**: V1 vision alignment — phased storyteller, living World
> Bible substrate, typed choices + meta-questions, multi-turn setup wizard,
> transactional rewrite, on-demand research, leakage guard. See
> [`docs/vision.md`](docs/vision.md) for the design targets and
> [`CHANGELOG.md`](CHANGELOG.md) for per-phase deliverables.


Fable 2.0 is a complete architectural paradigm shift from traditional "prompt-chained" AI Dungeon Masters. Built entirely on the **Google ADK 2.0 Beta** framework, it abandons fragile `while` loops and monolithic prompts in favor of a strictly typed Directed Acyclic Graph (DAG), native map-reduce research swarms, and an event-sourced timeline.

It acts as an uncompromising AI Game Master, utilizing a multi-agent tool-calling loop, a local GraphRAG memory system, and an interactive state machine to simulate living narrative worlds.

## 🚀 Key Features

*   **Deterministic Orchestration:** Control flow is managed by the ADK `Workflow` Graph. The `Storyteller` writes prose, the `Auditor` checks it against canon rules, and the `Archivist` mutates the persistent state using tools. If an LLM hallucinates, the graph catches the failure and explicitly routes backward to regenerate.
*   **Event-Sourced Timelines:** The database doesn't just hold the "current" state; it holds an immutable ledger of every event. If you click **"Undo"**, the native ADK `rewind_async()` API flawlessly reconstructs the timeline backward to the exact millisecond before the mistake.
*   **Parallel Research Swarm:** Fable 2.0 can handle wild crossover fanfiction out-of-the-box. Inputting a prompt dynamically spawns a parallel swarm of `LoreHunter` agents (via ADK's `parallel_worker=True`) that execute Google Searches and scrape wikis simultaneously, synthesizing the rules of the crossover into a rigid "World Bible" before Chapter 1 begins.
*   **Semantic Suspicion Engine:** Using local Ollama `pgvector` embeddings, the engine calculates real-time cosine similarity between the generated prose and hidden "forbidden concepts." If the protagonist brushes up against a secret, the engine mathematically detects the subtext and dynamically shifts the interactive UI into a 4-tier "Awareness Spectrum."
*   **Dynamic Prompt Assembly:** Replaces "Super Prompts." Micro-agents receive highly targeted instructions via ADK Plugins only when necessary (e.g., injecting an aggressive "Anti-Nerf" prompt if the protagonist operates on a continental scale). See [PROMPTING_STRATEGY.md](docs/PROMPTING_STRATEGY.md).

---

## ✨ What's New (Phases 12 + 13)

**Phase 12 — Suspicion Engine (Live):** The semantic dramatic-irony detector now actually fires. When generated prose embeds within cosine `0.78` of a hidden forbidden concept, the choice generator's system prompt is steered (via `before_model_callback`) into a 4-tier output `{text, tier}` where `tier ∈ {oblivious, uneasy, suspicious, breakthrough}`. The UI renders these as **slate / amber / orange / rose-pulse** buttons. *Earlier hook misuse + a state-access typo had silently masked Phase 12 from ever firing — both fixed.*

**Phase 13 — ADK Native Alignment & UI State Surface:** Major realignment to ADK 2.0 public APIs. Replaced reinvented plugins with bundled `GlobalInstructionPlugin` + `LoggingPlugin`, attached `state_schema=FableAgentState`, switched to `ctx.state.to_dict()` over private `_value`/`_delta`, made the recovery node reachable, and wired `LoreEdge` upserts on significant trust shifts. New `state_update` WebSocket event surfaces strain, cast, divergences, mood, chapter, and timeline date — the React UI now renders a **strain bar** (red-pulse when `>80`), a **tabbed sidebar** (Lore / Cast / Divergences), an **inline rewrite modal** with quick-pick chips, and a **header info row**. See [`FABLE_2_0_PLAN.md`](FABLE_2_0_PLAN.md) §10 for the verification status map and [`CHANGELOG.md`](CHANGELOG.md) for the full diff.

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

**Backend** — at the project root (`.env`):
```bash
echo "GEMINI_API_KEY=your_google_ai_studio_key" > .env
```
The Gemini key powers the Storyteller, Archivist, and the explicit `LlmEventSummarizer` used by ADK's `EventsCompactionConfig`. The summarizer must be passed explicitly because Fable's `root_agent` is a `Workflow`, not an `LlmAgent` — ADK's `_ensure_compaction_summarizer` can't auto-instantiate one in that case.

**Frontend** — optional, at `frontend/.env.local`:
```bash
# Defaults if unset
VITE_API_BASE=http://localhost:8001
VITE_WS_BASE=ws://localhost:8001
```
The frontend exposes these as `import.meta.env.VITE_*`. Useful when you deploy the backend to a non-localhost URL.

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