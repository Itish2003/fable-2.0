# Phase 4: Deterministic Graph Workflow Orchestration

## 1. Objective
Wire the individual Nodes from Phase 2 and Phase 3 together into an absolute, deterministic execution graph. This phase replaces programmatic loops and LLM-based routing with explicit ADK 2.0 `EdgeItems`, ensuring 100% reliability in the Narrative -> Audit -> Archive sequence.

## 2. Core ADK 2.0 Primitives
*   `google.adk.workflow.Workflow`: The state machine execution engine.
*   `google.adk.workflow._graph_definitions.EdgeItem`: Defines explicit node-to-node transitions.
*   `google.adk.workflow._function_node.FunctionNode`: For synchronous, Python-based logic gates (Auditor).
*   `google.adk.workflow._join_node.JoinNode`: For synchronizing parallel threads.

## 3. Technical Architecture

### The `FableWorkflow` Graph
Defined in `src/graph/workflow.py`.

**Nodes:**
1.  `CommandParser` (`FunctionNode`): Evaluates user input.
2.  `LoreHunter_1` .. `LoreHunter_N` (`LlmAgentWrapper`): Parallel research threads.
3.  `LoreSync` (`JoinNode`): Waits for all Hunters to finish.
4.  `Storyteller` (`LlmAgentWrapper`): Generates prose.
5.  `ChoiceGenerator` (`LlmAgentWrapper`): Generates the 4 user options.
6.  `Auditor` (`FunctionNode`): Evaluates Epistemic limits and Anti-Worf rules.
7.  `Archivist` (`LlmAgentWrapper`): Mutates state via tools.

**Edges (Routing Logic):**
*   *Input starts with `/research`:* `CommandParser` -> `LoreHunter` -> `LoreSync` -> END.
*   *Normal Input:* `CommandParser` -> `Storyteller` -> `ChoiceGenerator` -> `Auditor`.
*   *Audit Fails:* `Auditor` -> `Storyteller` (with `RetryException` payload).
*   *Audit Critical Fail:* `Auditor` -> SUSPEND (HITL `RequestInput`).
*   *Audit Passes:* `Auditor` -> `Archivist` -> END.

## 4. Step-by-Step Implementation

1.  **Define the Graph Structure:**
    *   Instantiate the `Workflow` class.
    *   Register all Nodes created in previous phases.
2.  **Implement the Auditor Logic Gate:**
    *   Create `src/nodes/auditor.py` as a `FunctionNode`.
    *   Write the Python logic to check `AgentState` limits against the `Storyteller`'s generated text.
3.  **Wire the Edges:**
    *   Define the `EdgeItems`, specifically implementing the conditional loops (e.g., Auditor failure routing back to Storyteller).
4.  **Implement HITL Hooks:**
    *   Use `_workflow_hitl_utils.py` to trigger suspensions when the Auditor detects a critical canon break requiring user authorization.

## 5. Validation Criteria
*   [ ] A standard user input successfully flows through Storyteller -> ChoiceGenerator -> Auditor -> Archivist.
*   [ ] A detected Anti-Worf violation forces the graph to route backward, regenerating the Storyteller's output without crashing.
*   [ ] Parallel `LoreHunter` nodes successfully block the graph at the `JoinNode` until all complete.
