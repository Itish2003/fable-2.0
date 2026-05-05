# Phase 3: Collaborative Node Configuration & Tooling

## 1. Objective
Transform the legacy string-parsing V1 agents into highly specialized, isolated ADK 2.0 Nodes. This phase configures the Creative node (`Storyteller`), the Analytical node (`Archivist`), and their associated tool belts and global plugins.

## 2. Core ADK 2.0 Primitives
*   `google.adk.workflow._llm_agent_wrapper.LlmAgentWrapper`: Wraps native ADK agents into Graph Nodes.
*   `google.adk.planners.plan_re_act_planner.PlanReActPlanner`: Forces the LLM to output structured plans and valid JSON tool arguments.
*   `google.adk.plugins.GlobalInstructionPlugin`: Modulates tone and style dynamically.
*   `google.adk.optimization.GEPARootAgentPromptOptimizer`: For automated prompt evaluation.

## 3. Technical Architecture

### A. The Tool Belt
Created in `src/tools/archivist_tools.py`. These tools natively mutate `FableAgentState`.
*   `update_relationship(target: str, trust_delta: int, tags: list[str])`
*   `record_divergence(event_id: str, description: str)`
*   `track_power_strain(power_id: str, strain_level: int)`
*   `advance_timeline(date_str: str)`

### B. Node Configuration
*   **`StorytellerNode`**: 
    *   *Model:* `gemini-3.1-flash-lite-preview`
    *   *Prompt:* Purely creative, stripped of formatting rules.
    *   *Context:* Fed dynamically by the Phase 2 GraphRAG.
*   **`ArchivistNode`**:
    *   *Model:* `gemini-3.1-flash-lite-preview` (for speed, determinism, and cost efficiency).
    *   *Planner:* `PlanReActPlanner(tool_choice="any")` (Forces tool usage, replacing V1's `_fallback_integrate_research`).
    *   *Tools:* The Tool Belt defined above.

### C. Dynamic Tone (GlobalInstructionPlugin)
*   Reads `AgentState.power_debt`. If `power_debt > 80`, the plugin prepends: *"INSTRUCTION: The protagonist is severely exhausted. Emphasize physical toll and limit complex magic."* to the `StorytellerNode` prompt just-in-time.

## 4. Step-by-Step Implementation

1.  **Develop ADK Tools:**
    *   Implement the Python functions for the Tool Belt with strict Pydantic docstrings (required for Gemini tool calling).
2.  **Configure LlmAgentWrappers:**
    *   Create `src/nodes/storyteller.py` and `src/nodes/archivist.py`.
    *   Wrap `LlmAgent` instances, assigning Gemini 1.5 Pro and Flash respectively.
3.  **Implement Plugins:**
    *   Write the `GlobalInstructionPlugin` logic to map `AgentState` variables to tone instructions.
    *   Enable the `ReflectAndRetryToolPlugin` on the Archivist.
4.  **Setup GEPA Optimization (Optional/Advanced):**
    *   Create an `EvalSet` of 5 high-quality V1 chapters and run the `GEPARootAgentPromptOptimizer` to refine the Storyteller's base prompt.

## 5. Validation Criteria
*   [ ] `ArchivistNode` successfully parses a prose chapter and invokes `record_divergence` with valid JSON.
*   [ ] High `power_debt` state successfully alters the generated prose of the `StorytellerNode`.
*   [ ] Failed tool calls automatically trigger internal retries without crashing the node execution.
