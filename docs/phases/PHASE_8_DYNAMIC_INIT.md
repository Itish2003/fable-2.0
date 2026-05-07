# Phase 8: Advanced Dynamic Initialization & Research Swarm

## 1. Objective
Restore the V1 "World-Generation Pipeline" capability within the Fable 2.0 ADK engine. This phase implements a dynamic, parallel research swarm that analyzes crossover prompts, executes dual-stream research (Local pgvector + Web Search), and synthesizes a canonical world-bible into the persistent session state before the story begins.

## 2. Core ADK 2.0 Primitives
*   `parallel_worker=True`: Native ADK 2.0 node modifier that automatically fans out execution for iterable inputs.
*   `google.adk.tools.google_search_tool.GoogleSearchTool`: Built-in web grounding tool.
*   `google.adk.tools.load_web_page.load_web_page`: Built-in URL scraping function.
*   `LlmAgent` with `PlanReActPlanner`: For the Lore Keeper's synthesis phase.
*   `RequestInput`: For the multi-turn Clarification and Review flow in the UI.

## 3. Technical Architecture

### A. The Initialization Sub-Graph
The `build_fable_workflow` will be updated to insert a high-fidelity boot sequence:
1.  **WorldBuilderNode** (Existing): Collects the raw prompt.
2.  **QueryPlannerNode** (New): Analyzes the prompt to generate an Array of research topics.
3.  **LoreHunterSwarm** (New): A single `LoreHunter` agent wrapped with `parallel_worker=True`. The ADK natively spawns instances for each query in the array.
4.  **LoreKeeperNode** (New): Receives the aggregated list of results and fuses them into `ctx.state`.
5.  **ApprovalNode** (New): HITL suspension to show the user the "World Primer" before Chapter 1.

### B. Dual-Stream Research Philosophy
The `LoreHunter` nodes will not choose between local and web data; they will use both:
*   **Postgres Diver**: Pulls raw novel prose related to the query for narrative texture.
*   **Web Scraper**: Pulls structured wiki data for hard rule enforcement (Anti-Worf/Forbidden Knowledge).

### C. State Mapping (Parity with V1)
The `LoreKeeper` will strictly populate these keys in `ctx.state`:
*   `magic_system`: Rules, limitations, and power scaling.
*   `character_voices`: Speech patterns and verbal tics for key NPCs.
*   `knowledge_boundaries`: Comprehensive list of meta-knowledge the POV must not know.
*   `canon_character_integrity`: Minimum competence rules to prevent "jobbing."

## 4. Step-by-Step Implementation

1.  **Implement the Planner & Swarm Nodes:**
    *   Create `src/nodes/init_research.py`.
    *   Define `run_query_planner` (LLM) and the dynamic `run_lore_hunter` (Tool-based).
2.  **Implement the Lore Keeper (Synthesizer):**
    *   Create `src/nodes/lore_keeper.py` as an `LlmAgent`.
    *   Configure it with the `PlanReAct` logic to structure the massive data dump.
3.  **Update the Workflow Graph:**
    *   Modify `src/graph/workflow.py` to wire the new nodes between `WorldBuilder` and `Storyteller`.
    *   Implement the `ApprovalNode` suspension.
4.  **Update the Frontend UI:**
    *   Add a `ResearchStatus` component to stream the swarm's activity.
    *   Add the `ReviewStep` to the `SetupWizard.tsx` to handle the final approval.

## 5. Validation Criteria
*   [x] A crossover prompt correctly triggers multiple parallel `LoreHunter` runs.
*   [x] The `LoreKeeper` successfully populates `ctx.state["anti_worf_rules"]` with data fetched from the web.
*   [x] The UI successfully renders the "World Primer" summary and waits for the "Ignite" command.
*   [x] The `Storyteller` uses the newly researched crossover data in the very first paragraph of Chapter 1.
