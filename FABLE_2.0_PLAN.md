# Fable 2.0: Uncompromised Architectural Masterplan

## Executive Summary
Fable 2.0 is a complete departure from the "Manual JSON Orchestration" of V1. It is a pure-native implementation built on the **ADK 2.0 Beta** framework, leveraging its most advanced primitives: **Graph-Based Workflows**, **Node Isolation**, and **VertexAI GraphRAG**. 

This plan assumes a **Clean Slate Strategy**: We are discarding all V1 story data and backward compatibility requirements to ensure the V2 implementation is 100% optimized for performance, scalability, and narrative integrity.

---

## 1. Exhaustive V1 to V2 Migration Map

To guarantee nothing is lost from V1, every legacy file and module has an explicit ADK 2.0 migration path.

### WebSocket Actions (`src/ws/actions/`)
| V1 File | V2 Graph Architecture Mapping |
| :--- | :--- |
| `choice.py` | Maps to `ChoiceGeneratorNode`, executing after the `StorytellerNode`. |
| `research.py` & `enrich.py` | Handled by `LoreHunterNode` parallel edges branching from the `DirectorNode`. |
| `rewrite.py` | Edge loop pointing back to `StorytellerNode` with `Refiner` instructions. |
| `undo.py` & `reset.py` | Handled natively by ADK `DatabaseSessionService` (reverting to a prior event checkpoint). |
| `bible_snapshot.py` | Deprecated. ADK natively checkpoints the `AgentState` on every turn. |
| `bible_diff.py` | Natively achieved by comparing the Pydantic `AgentState` of checkpoint $N$ vs $N-1$. |

### Utilities (`src/utils/`)
| V1 File | V2 Graph Architecture Mapping |
| :--- | :--- |
| `bible_delta_processor.py` | Decomposed into strict, atomic ADK Tools (`update_relationship`, etc.). |
| `lore_keeper_processor.py` | Logic merged into the `ArchivistNode` prompt and tools. |
| `fk_detector.py` | Upgraded to Epistemic Graph Filtering in the `AuditorNode`. |
| `json_extractor.py` | **Deprecated.** ADK's `PlanReActPlanner` natively enforces valid JSON output. |
| `resilient_client.py` | **Deprecated.** Replaced by ADK 2.0's native `RetryConfig` on Nodes. |
| `universe_config.py` | Migrated to the `WorldBuilderNode` state initialization logic. |
| `logging_config.py` | Replaced by ADK 2.0's native `LoggingPlugin` and `TelemetryContext`. |

### Tools & Schemas (`src/tools/`, `src/schemas/`)
| V1 File | V2 Graph Architecture Mapping |
| :--- | :--- |
| `source_text.py` | Upgraded to a background `LoreIngestionNode` (ETL for GraphRAG). |
| `meta_tools.py` | Legacy sub-runner management replaced by native `JoinNode` parallel execution. |
| `core_tools.py` | Data mutation tools ported directly to the `ArchivistNode`'s tool belt. |
| `world_bible_complete_schema.py` | Converted directly into the ADK 2.0 `FableAgentState` Pydantic model. |

### API Routers (`src/routers/`)
| V1 File | V2 Graph Architecture Mapping |
| :--- | :--- |
| `setup.py` | Replaced by the `WorldBuilderNode` using `RequestInput` for interactive setup. |
| `branches.py` | Replaced by spawning new ADK sessions with a `parent_session_id`. |
| `stories.py` | Endpoint triggers the initial `FableWorkflow._run_impl()` graph execution. |

---

## 2. Core Orchestration: Deterministic Graph Workflows

Fable 2.0 moves from programmatic Python loops to a formal state machine using `google.adk.workflow.Workflow`.

### The Graph Engine (`FableWorkflow`)
*   **Absolute Predictability:** Every interaction is defined by a validated graph of Nodes and Edges (`EdgeItem`). 
*   **The Pipeline Flow:**
    1.  **Entry Node:** Receives user WebSocket command.
    2.  **Logic Node (`FunctionNode`):** Parses the command (`/research`, `/rewrite`, `/choice`) and directs execution to the appropriate branch via conditional edges.
    3.  **Research Branch:** Parallel `LoreHunterNode` (`LlmAgentWrapper`) instances fetch data, reconvening at a **`JoinNode`** to synchronize state.
    4.  **Narrative Branch:** `StorytellerNode` (`LlmAgentWrapper`) generates prose.
    5.  **Interactive Branch:** `ChoiceGeneratorNode` (`LlmAgentWrapper`) executes immediately after the Storyteller to generate the "4 Choices", maintaining its own state to adapt to the player's playstyle.
    6.  **Audit Branch:** `AuditorNode` (`FunctionNode`) enforces Epistemic Boundaries and Anti-Worf rules via Python logic.
    7.  **Archive Node:** `ArchivistNode` (`LlmAgentWrapper` + `ToolNode` configured with `PlanReActPlanner`) performs atomic state mutations via tools.

---

## 2. The Lore Engine: GraphRAG & Primary Source Ingestion

We are replacing the flat `world_bible.json` with a **Dynamic Knowledge Graph** (NetworkX/Vector-backed) integrated via the `VertexAiRagMemoryService`.

### Primary Source Ingestion (Bypassing Surface-Level AI)
*   **The V1 Masterstroke:** Inspection of the legacy `source_text` PSQL database revealed that Fable does *not* rely on generic Google Searches or Wiki scrapes. It was seeded with **literal source material** (e.g., *Mahouka* Light Novel Volumes 1-8, comprising hundreds of thousands of words). Generic web-search agents return surface-level summaries; Fable requires the granular, exact prose of the original author.
*   **The V2 ETL Pipeline (`LoreIngestionNode`):** The legacy PyPDF/Playwright logic is upgraded to an asynchronous ETL worker. This node ingests massive, raw manuscript volumes (50k-90k words each), chunks them, and embeds them directly into the GraphRAG Vector DB, ensuring the `LoreHunterNode` queries the *actual books*, not Wikipedia.

### Context Engineering via Subgraph Injection
*   **The Radius Pattern:** Instead of injecting the whole Bible, the `MemoryService` performs a graph traversal from the scene's focus node (e.g., a character or location). 
*   **Epistemic Filtering (Replacing `fk_detector.py`):** Graph edges contain "visibility" weights. The injection engine *physically cannot* pull lore nodes that are hidden from the current POV character, rendering "Soft Forbidden Knowledge" leaks impossible.

---

## 3. The ADK 2.0 Tool Belt (State Mutation)

The `ArchivistNode` strictly mutates the Pydantic `AgentState` using these core tools. Because it uses `PlanReActPlanner(tool_choice="any")`, it is mathematically forced to output valid schema, eliminating all legacy `bible_validator.py` regexes.

| Tool Name | Parameters | Impact |
| :--- | :--- | :--- |
| `update_relationship` | `target, trust_level, dynamic_tags` | Mutates the graph edge weights. |
| `record_divergence` | `canon_event_id, deviation_desc` | Generates a new Timeline Node in the graph. |
| `track_power_strain`| `power_id, level` | Updates `AgentState.power_debt` for narrative balancing. |
| `commit_lore` | `entity_name, metadata_dict` | Finalizes a background research pass into the graph. |
| `advance_timeline` | `new_date, event_description` | Allows the Storyteller to explicitly move the world clock forward. |

---

## 4. Systemic Constraints & Integrity

### Anti-Worfing & Protection
*   **Protected Character Nodes:** Canon characters (Tatsuya, Miyuki) have immutable `minimum_competence` attributes. 
*   **Auditor Enforcement:** The `AuditorNode` runs a Python block that compares `Storyteller` output against these attributes. If the Storyteller "nerfs" a protected character, the graph directs an edge back to the `StorytellerNode` with a `RetryException`.

### Power Debt & Tone Management
*   **Strain Tracking:** Protagonist powers are linked to a `strain_level` attribute in the `AgentState`. 
*   **GlobalInstructionPlugin:** High strain automatically triggers the `GlobalInstructionPlugin` to prepend "exhaustion" or specific aesthetic constraints to the next Storyteller prompt, stripping this logic out of the monolithic V1 prompt.

### Branching & Family Tree
*   **Session Tree Manager (`branches.py`):** Branching is handled by starting a new `DatabaseSessionService` session passing the `parent_session_id`. The `/family-tree` API simply maps this native session hierarchy.

### Human-in-the-Loop (HITL) Authorization
*   **The ADK 2.0 Feature:** Leveraging `_workflow_hitl_utils.py` to suspend graph execution.
*   **The Workflow:** If the `AuditorNode` detects a "Critical Divergence" (e.g., permanent death of a protected canon character), the graph does not automatically loop back. Instead, it enters a `SUSPENDED` state and emits a `RequestInput` event: *"The Storyteller has proposed a major canon break: [Description]. Do you authorize this deviation?"* This gives you final editorial control over the timeline.

---

## 5. Core Philosophy & Engineering Principles

Fable 2.0 is built on the engineering philosophy extracted from the **ADK 2.0 Beta (v2.0.0-beta.1)** commit history:

1.  **Deterministic Orchestration over Prompt-Based Routing:**
    *   *Principle:* Replace "black-box" routing with explicit Graph-Based Workflows (`c25d86f1`). 
    *   *Implementation:* We use `EdgeItem` definitions to guarantee the system never "hallucinates" the next narrative step.
2.  **State Reconstruction over JSON Injection:**
    *   *Principle:* Utilize event-based state reconstruction (`ca327329`) for native resumability and Human-in-the-Loop (HITL) support.
    *   *Implementation:* State is reconstructed by the ADK `SessionService` from previous tool events.
3.  **Execution Isolation:**
    *   *Principle:* Rely on `NodeRunner` isolation (`0b3e7043`) to ensure a failure in a Research Node doesn't crash the Storyteller.
    *   *Implementation:* Each narrative node is a self-contained unit with its own retry (`RetryConfig`) and validation logic.

---

## 6. Implementation Roadmap

1.  **Phase 1: Pure State Model**
    *   Define the `FableAgentState` Pydantic model (No V1 legacy fields).
    *   Setup the `DatabaseSessionService` for native branching.
2.  **Phase 2: GraphRAG Infrastructure**
    *   Initialize `VertexAiRagMemoryService`.
    *   Build the graph traversal logic for context injection and Epistemic Filtering.
3.  **Phase 3: Node Configuration**
    *   Build the `StorytellerNode`, `ArchivistNode`, and `LoreHunterNode` wrappers.
    *   Implement the `GlobalInstructionPlugin` for modular prompt engineering.
4.  **Phase 4: Workflow Orchestration**
    *   Construct the `Workflow` object with all `EdgeItem` definitions, including the `JoinNode` and `AuditorNode` logic.
    *   Implement the `/family-tree` API by traversing the ADK Session Graph.
5.  **Phase 5: World Simulation Boot**
    *   Implement the `WorldBuilderNode` (`FunctionNode`) for interactive `/setup` using `RequestInput`.

---

## Conclusion
By embracing ADK 2.0's deterministic graphs, node isolation, and memory services, we are trading thousands of lines of brittle V1 glue code for a declarative, state-accurate simulation of a narrative universe. The architecture is clean, native, and infinitely scalable.