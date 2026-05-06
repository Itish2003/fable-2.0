# Phase 7: Productionization & Advanced Telemetry

## 1. Objective
Harden the Fable 2.0 application for production use. This phase focuses on activating ADK 2.0's native telemetry, cost-tracking, cache optimization, and automated error recovery to ensure the engine runs reliably and cost-effectively at scale.

## 2. Core ADK 2.0 Primitives
*   `google.adk.models.lite_llm.UsageMetadataChunk`: Provides token counts and cache hit rates.
*   `google.adk.plugins.logging_plugin.LoggingPlugin`: Native plugin for structured event observation.
*   `google.adk.apps.compaction.EventsCompactionConfig`: Triggers automated summarization to prevent context exhaustion.

## 3. Technical Architecture

### A. Context Caching & Compaction (`src/plugins/telemetry.py`)
*   We implement a custom `TelemetryPlugin` (or extend the native `LoggingPlugin`).
*   **The Trigger:** It observes the `UsageMetadataChunk` on every `LlmResponse`. 
*   **The Action:** If `cached_prompt_tokens` approaches 0 (indicating a cache miss or context overflow), or if the total token count exceeds a predefined threshold (e.g., 80% of the model's limit), the plugin invokes the `EventsCompactionConfig`.
*   **The Result:** ADK natively summarizes older events in the session, maintaining narrative coherence while freeing up space for new prose.

### B. "Reasoning Token" Integration
*   The telemetry plugin extracts the `reasoning_tokens` value from the Gemini 1.5 Pro response.
*   We route this metric into the `AgentState.power_debt` calculation. If the model had to use massive reasoning overhead to resolve a complex magic interaction, the protagonist incurs higher narrative strain.

### C. Graceful Degradation & Error Recovery
*   If a node throws an API rate limit error or a strict Pydantic validation error (e.g., the Archivist fails a tool call multiple times despite `ReflectAndRetry`), the exception propagates up to the Graph Runner.
*   **The Recovery Edge:** We define a `RecoveryNode`. If an exception occurs, the graph routes here. The Recovery node emits a system message to the WebSocket ("The weave is unstable. Rewriting destiny...") and attempts to execute the node again with a lower temperature setting or a simplified prompt.

## 4. Step-by-Step Implementation

1.  **Implement the Telemetry Plugin:**
    *   Create `src/plugins/telemetry.py`. Write the callbacks to intercept and log `UsageMetadataChunk` data.
2.  **Configure Session Compaction:**
    *   Add `EventsCompactionConfig` to the global `App` container definition in `app_container.py`.
3.  **Wire Reasoning Tokens to State:**
    *   Update the `track_power_strain` tool or the Telemetry plugin to dynamically adjust state based on the model's output effort.
4.  **Implement the Recovery Node (Optional):**
    *   Add a `RecoveryNode` to the workflow graph and define the error-catching edges.

## 5. Validation Criteria
*   [ ] The Telemetry plugin successfully logs `prompt_tokens`, `cached_prompt_tokens`, and `reasoning_tokens` to the console for every LLM turn.
*   [ ] Pushing the session past the token threshold automatically triggers a compaction event, reducing the total session token count without losing core plot elements.
*   [ ] A simulated API failure is successfully caught and routed to the Recovery Node without severing the WebSocket connection.
