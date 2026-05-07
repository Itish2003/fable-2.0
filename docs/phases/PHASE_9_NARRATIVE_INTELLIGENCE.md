# Phase 9: Narrative Intelligence & Long-Term Continuity

## 1. Objective
Restore the high-intelligence features from V1 that managed long-term narrative memory, interactive story branching, and mid-simulation research. This phase focuses on making the engine "smarter" during the active game loop, ensuring the Storyteller remains lore-accurate even in late-game chapters.

## 2. Core ADK 2.0 Primitives
*   `ctx.rewind()` / `rewind_before_invocation_id`: Native ADK capability for the Undo/Rewind feature.
*   `LlmAgent` with `ChoiceGenerator` role: To generate the 4 narrative branches.
*   `AgentPlugin.before_agent_callback`: To inject the rolling "Chapter Summaries" and metadata into the Storyteller's prompt.
*   `Condition-Based Routing`: To detect "Research Intent" in player choices and route to the LoreHunter swarm mid-story.

## 3. Technical Architecture

### A. Mid-Story Auto-Research (Active Hunter)
Update the `EntryNode` or a dedicated `IntentAnalyzerNode` to scan player input for research requests (e.g., "I want to research X").
*   **Routing**: If intent is detected, route to `LoreHunterSwarm` -> `LoreKeeper` before hitting the `Storyteller`.
*   **State Persistence**: Results are merged into the same `crossover_primer` state used in Phase 8.

### B. Long-Term Memory (Rolling Summaries)
Implement a `SummaryPlugin` that maintains a dedicated `ctx.state["narrative_history"]`.
*   **Action**: After every `Storyteller` turn, the `Archivist` (or a dedicated `SummarizerNode`) generates a 2-sentence summary of the chapter.
*   **Injection**: The `SummaryPlugin` prepends the last 10 chapter summaries and the "Current Stakes" to every Storyteller request.

### C. The Choice Generator
Add a final node to the core loop: `Storyteller` -> `Auditor` -> `Archivist` -> **`ChoiceGeneratorNode`**.
*   **Output**: Returns 4 JSON objects representing potential next steps, which the React UI renders as buttons.

### D. Undo & Rewrite Mechanisms
Expose ADK 2.0's event-sourcing capabilities to the UI.
*   **Undo**: A WebSocket action that triggers `ctx.rewind()` to the previous `turn_complete` event.
*   **Rewrite**: A WebSocket action that re-triggers the `StorytellerNode` with a "Negative Constraint" (e.g., "Don't mention the fire this time").

## 4. Step-by-Step Implementation

1.  **Implement the Choice Generator:**
    *   Create `src/nodes/choice_generator.py`.
    *   Wire it into the workflow in `src/graph/workflow.py`.
2.  **Implement Narrative Summarization:**
    *   Update `src/nodes/archivist.py` or create `src/nodes/summarizer.py` to produce rolling summaries.
    *   Update `src/state/models.py` to include a `List[str]` for `chapter_summaries`.
3.  **Implement Intent Detection (Mid-Story Research):**
    *   Create a `RouterNode` that uses Regex or a fast LLM to detect if the user is asking to "Research" or "Look up" something.
    *   Update the Graph DAG to allow mid-loop research transitions.
4.  **Expose Rewind & Regenerate:**
    *   Update `src/ws/manager.py` and `src/ws/runner.py` to handle `undo` and `rewrite` commands.
    *   Update the React `StoryView.tsx` to include the control buttons.

## 5. Validation Criteria
*   [ ] The UI displays 4 clickable choices after every story update.
*   [ ] Clicking "Undo" successfully removes the last chapter and reverts the `ctx.state` (e.g., power strain resets).
*   [ ] Typing "Research the history of the Yotsuba" in the chat triggers the Swarm mid-story.
*   [ ] Chapter 10 of a story successfully references an event from Chapter 1 that was captured in the rolling summary.
