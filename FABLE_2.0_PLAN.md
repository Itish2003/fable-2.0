# Fable 2.0: Uncompromised Architectural Masterplan

## Executive Summary
Fable 2.0 is a complete departure from the "Manual JSON Orchestration" of V1. It is a pure-native implementation built on the **ADK 2.0 Beta** framework, leveraging its most advanced primitives: **Graph-Based Workflows**, **Collaborative Agent Teams**, and **VertexAI GraphRAG**. 

This plan assumes a **Clean Slate Strategy**: We are discarding all V1 story data and backward compatibility requirements to ensure the V2 implementation is 100% optimized for performance, scalability, and narrative integrity.

---

## 1. Core Orchestration: Deterministic Graph Workflows

Fable 2.0 moves from programmatic Python loops to a formal state machine using `google.adk.workflow.Workflow`.

### The Graph Engine (`FableWorkflow`)
*   **Absolute Predictability:** Every interaction is defined by a validated graph of Nodes and Edges (`EdgeItem`). 
*   **The Pipeline Flow:**
    1.  **Entry Node:** Receives user WebSocket command.
    2.  **Logic Node (`FunctionNode`):** Parses command and directs to the appropriate branch.
    3.  **Research Branch:** Parallel `LoreHunterNode` instances fetch data, reconvening at a **`JoinNode`**.
    4.  **Narrative Branch:** `StorytellerNode` generates prose.
    5.  **Audit Branch:** `AuditorNode` (`FunctionNode`) enforces Epistemic Boundaries and Anti-Worf rules.
    6.  **Archive Node:** `ArchivistNode` performs atomic state mutations via tools.

---

## 2. The Lore Engine: GraphRAG & Epistemic Boundaries

We are replacing the flat `world_bible.json` with a **Dynamic Knowledge Graph** (NetworkX/Vector-backed).

### Context Engineering via Subgraph Injection
*   **The Radius Pattern:** Instead of injecting the whole Bible, the `MemoryService` performs a graph traversal from the scene's focus node (e.g., a character or location). 
*   **Epistemic Filtering:** Graph edges contain "visibility" weights. The injection engine *physically cannot* pull lore nodes that are hidden from the current POV character, rendering "Soft Forbidden Knowledge" leaks impossible.
*   **ETL Pipeline:** The legacy `source_text.py` is upgraded to a `LoreIngestionNode` that scrapes LN/Manga wikis directly into the GraphRAG.

---

## 3. Collaborative Agent Roles

Nodes are configured with specific ADK 2.0 Collaborative Modes:

| Node Name | Model | Mode | Responsibility |
| :--- | :--- | :--- | :--- |
| `Storyteller` | Gemini 1.5 Pro | `task` | High-creativity prose; yields to WebSocket. |
| `Archivist` | Gemini 1.5 Flash | `single_turn` | Atomic `AgentState` mutation via `PlanReActPlanner`. |
| `LoreHunter` | Gemini 1.5 Flash | `single_turn` | Targeted wiki search and Graph population. |
| `WorldBuilder`| Gemini 1.5 Pro | `task` | Interactive `/setup` wizard using `RequestInput`. |

---

## 4. The ADK 2.0 Tool Belt (State Mutation)

The `Archivist` strictly mutates the Pydantic `AgentState` using these core tools:

| Tool Name | Parameters | Impact |
| :--- | :--- | :--- |
| `update_relationship` | `target, trust_level, dynamic_tags` | Mutates the graph edge weights. |
| `record_divergence` | `canon_event_id, deviation_desc` | Generates a new Timeline Node in the graph. |
| `track_power_strain`| `power_id, level` | Updates `AgentState.power_debt` for narrative balancing. |
| `commit_lore` | `entity_name, metadata_dict` | Finalizes a background research pass into the graph. |

---

## 5. Systemic Constraints & Integrity

### Anti-Worfing & Protection
*   **Protected Character Nodes:** Canon characters (Tatsuya, Miyuki) have immutable `minimum_competence` attributes. 
*   **Auditor Enforcement:** The `AuditorNode` runs a Python block that compares `Storyteller` output against these attributes. If the Storyteller "nerfs" a protected character, the graph loops back with a `RetryException`.

### Power Debt
*   Protagonist powers are linked to a `strain_level` attribute in the `AgentState`. High strain automatically triggers the `GlobalInstructionPlugin` to prepend "exhaustion" constraints to the next Storyteller prompt.

---
---

## 8. Core Philosophy & Engineering Principles

Fable 2.0 is built on the engineering philosophy extracted from the **ADK 2.0 Beta (v2.0.0-beta.1)** commit history:

1.  **Deterministic Orchestration over Prompt-Based Routing:**
    *   *Principle:* Replace "black-box" routing with explicit Graph-Based Workflows (`c25d86f1`). 
    *   *Implementation:* We use `EdgeItem` definitions to guarantee the system never "hallucinates" the next narrative step.
2.  **State Reconstruction over JSON Injection:**
    *   *Principle:* Utilize event-based state reconstruction (`ca327329`) for native resumability and Human-in-the-Loop (HITL) support.
    *   *Implementation:* State is never passed as a string; it is reconstructed by the ADK `SessionService` from previous tool events.
3.  **Execution Isolation:**
    *   *Principle:* Rely on `NodeRunner` isolation (`0b3e7043`) to ensure a failure in a Research Node doesn't crash the Storyteller.
    *   *Implementation:* Each narrative node is a self-contained unit with its own retry and validation logic.
4.  **Transparent Evolution (Branching):**
    *   *Principle:* Leverage the framework's native support for "flushing" state deltas onto events.
    *   *Implementation:* Narrative branching is a first-class citizen, achieved by creating new sessions from specific event checkpoints.

---

## 9. Final Step-by-Step Transition Guide

...
    *   Setup the `DatabaseSessionService` for native branching.
2.  **Phase 2: GraphRAG Infrastructure**
...
    *   Initialize `VertexAiRagMemoryService`.
    *   Build the graph traversal logic for context injection.
3.  **Phase 3: Node Configuration**
    *   Build the `Storyteller` and `Archivist` nodes using the `GlobalInstructionPlugin`.
4.  **Phase 4: Workflow Orchestration**
    *   Construct the `Workflow` object with all `EdgeItem` definitions.
    *   Implement the `/family-tree` API by traversing the ADK Session Graph.
5.  **Phase 5: World Simulation Boot**
    *   Implement the `WorldBuilderNode` for interactive setup.

---

## Conclusion
Fable 2.0 is a next-generation narrative engine. By leveraging ADK 2.0's deterministic graphs and collaborative subagents, we are creating a system that is not just a text generator, but a **state-accurate simulation of a narrative universe**.

**The plan is now final. We are ready for implementation.**