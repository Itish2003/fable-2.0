# Fable 2.0: Uncompromised Architectural Masterplan

## Executive Summary
Fable 2.0 is a complete departure from the "Manual JSON Orchestration" of V1. It is a pure-native implementation built on the **ADK 2.0 Beta** framework, leveraging its most advanced primitives: **Graph-Based Workflows**, **Node Isolation**, **GraphRAG over local Postgres + pgvector + Ollama**, and **Native Telemetry**.

This plan assumes a **Clean Slate Strategy**: V1 story data and backward-compatibility requirements were discarded so the V2 implementation could be optimized for performance, scalability, and narrative integrity from the ground up.

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
| `fk_detector.py` | Upgraded to Epistemic Graph Filtering in the `AuditorNode` & GraphRAG. |
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
    3.  **Research Branch:** Parallel `LoreHunterNode` instances fetch data, reconvening at a **`JoinNode`** to synchronize state.
    4.  **Narrative Branch:** `StorytellerNode` generates prose.
    5.  **Interactive Branch:** `ChoiceGeneratorNode` executes immediately after the Storyteller to generate the "4 Choices".
    6.  **Audit Branch:** `AuditorNode` (`FunctionNode`) enforces Epistemic Boundaries and Anti-Worf rules via Python logic.
    7.  **Archive Node:** `ArchivistNode` (`LlmAgentWrapper` + `ToolNode` configured with `PlanReActPlanner`) performs atomic state mutations via tools.

---

## 3. The Lore Engine: GraphRAG & Primary Source Ingestion

We replace the flat `world_bible.json` with a **Dynamic Knowledge Graph** backed by Postgres + `pgvector` and exposed through a custom `FableLocalMemoryService` that subclasses ADK's `BaseMemoryService`. The local stack was chosen over `VertexAiRagMemoryService` to keep development friction low, run fully offline (no Vertex API quota), and use Ollama-hosted `nomic-embed-text:v1.5` embeddings — migration to Vertex remains trivial because the service interface is matched.

### Primary Source Ingestion (Bypassing Surface-Level AI)
*   **The V1 Masterstroke:** V1 history shows a reliance on raw Light Novel manuscripts (Volumes 1-8). 
*   **The V2 ETL Pipeline (`LoreIngestionNode`):** Asynchronous ETL worker that ingests raw manuscript volumes (50k-90k words each), chunks them, and embeds them via Ollama into Postgres+pgvector in parallel batches (`asyncio.gather` + per-batch commits — a transient embedding failure mid-volume doesn't abort persisted progress). The `LoreHunterNode` then queries the actual books, not Wikipedia.

### Context Engineering via Subgraph Injection
*   **The Radius Pattern:** Instead of injecting the whole Bible, the `MemoryService` performs a graph traversal from the scene's focus node.
*   **Epistemic Filtering (Replacing `fk_detector.py`):** Two-layer enforcement. (1) `memory_service.search_memory` filters retrieval against `state.forbidden_concepts` *before* the LLM sees results. (2) The `AuditorNode` substring-checks generated prose as a fallback. `LoreEdge.visibility_whitelist` carries the per-edge POV gate; `update_relationship` writes `["PROTAGONIST", target_name]` so private edges only resolve for those endpoints during graph traversal.

---

## 4. The ADK 2.0 Tool Belt (State Mutation)

The `ArchivistNode` strictly mutates the Pydantic `AgentState` using these core tools. The agent attaches `PlanReActPlanner()` (chain-of-thought tool routing) plus `GenerateContentConfig(tool_config=ToolConfig(function_calling_config=FunctionCallingConfig(mode='ANY')))` — `mode='ANY'` is the actual lever that forces the model to emit a tool call every turn, guaranteeing valid schema. *(Earlier drafts of this plan referenced a `tool_choice="any"` kwarg on the planner; that kwarg does not exist on `PlanReActPlanner` and was a documentation bug.)*

| Tool Name | Parameters | Impact |
| :--- | :--- | :--- |
| `update_relationship` | `target_name, type, trust, dynamics` | Mutates the graph edge weights and character disposition. |
| `record_divergence` | `canon_event_id, deviation_desc` | Generates a new Timeline Node in the graph to track butterfly effects. |
| `track_power_strain`| `power_id, level` | Updates `AgentState.power_debt` for narrative balancing. |
| `commit_lore` | `entity_name, metadata_dict` | Finalizes a background research pass into the graph. |
| `advance_timeline` | `new_date, event_description` | Allows the Storyteller to explicitly move the world clock forward. |
| `report_violation` | `type, character, concept, quote` | Logs lore breaks for the Auditor to review. |

---

## 5. Native Telemetry & Context Optimization

ADK 2.0 exposes native `usage_metadata` within its `LlmResponse` events (via the `UsageMetadataChunk` model). In V1, token usage was a black box leading to arbitrary truncation. In V2, we leverage this metadata programmatically:

### A. Context Caching Analytics
*   The `UsageMetadataChunk` tracks `prompt_tokens` vs `cached_prompt_tokens`. 
*   **The Upgrade:** We will implement an ADK `LoggingPlugin` that tracks cache hit rates for the `StorytellerNode`. If the `cached_prompt_tokens` ratio drops below a threshold, it automatically triggers an `EventsCompactionConfig` cycle to prune the context window, dramatically lowering API costs.

### B. Reasoning & Effort Tracking
*   The metadata exposes `reasoning_tokens`. 
*   **The Upgrade:** We tie this directly to the "Power Debt" constraint. If the `StorytellerNode` consumes excessive `reasoning_tokens` to resolve a complex battle scene, the system naturally increments the character's strain level.

### C. Error Observation
*   The `LlmResponse` contains native `error_code`, `error_message`, and `interrupted` flags.
*   **The Upgrade:** Rather than raw `try/except` blocks crashing the script, the `FableWorkflow` intercepts these explicit flags and routes them to a `RecoveryNode` that gracefully downgrades the prompt (e.g., bypassing GraphRAG to save tokens) before retrying.

---

## 6. Native ADK 2.0 Beta Superpowers (Aspirational — Not Yet Wired)

These ADK Beta features were identified in the source-code audit. They remain **aspirational**; nothing under this section is currently active in the runtime. Tagged honestly so the plan doesn't drift from reality.

### A. Automated Evaluation & Optimization (GEPA) — *aspirational*
*   **The Feature:** `google.adk.optimization.GEPARootAgentPromptOptimizer`.
*   **The Plan:** Define an `EvalSet` of "Perfect Chapters" from V1. Fable 2.0 *would* use GEPA to automatically refine the `StorytellerNode` system instructions to match a preferred prose style, replacing monolithic V1 manual prompt engineering.
*   **Status:** Not implemented. No `EvalSet` exists; no GEPA optimizer is attached to any agent.

### B. Native Tool Retries (`ReflectAndRetryToolPlugin`) — *aspirational*
*   **The Upgrade:** Would replace the manual "fix: enforce tool calls" logic in V1. If an agent failed a tool call, the framework would automatically reflect on the error and retry internally before the graph continues.
*   **Status:** Not wired. Current resilience comes from the auditor's retry counter (3 failures → `recovery_node`), not from tool-level retries.

---

## 7. Systemic Constraints & Integrity

### Anti-Worfing & Protection
*   **Protected Character Nodes:** Canon characters have immutable `minimum_competence` attributes. 
*   **Auditor Enforcement:** The `AuditorNode` runs a Python block that compares `Storyteller` output against these attributes. If the Storyteller "nerfs" a protected character, the graph loops back with a `RetryException`.

### Power Debt & Tone Management
*   **Strain Tracking:** Protagonist powers are linked to a `strain_level` attribute in the `AgentState`. 
*   **GlobalInstructionPlugin:** High strain automatically triggers the `GlobalInstructionPlugin` to prepend exhaustion or specific aesthetic constraints to the prompt.

### Human-in-the-Loop (HITL) Authorization
*   **The Workflow:** Leveraging `_workflow_hitl_utils.py`, if the `AuditorNode` detects a "Critical Divergence" (e.g., canon death), the graph enters a `SUSPENDED` state and emits a `RequestInput` event: *"The Storyteller has proposed a major canon break. Do you authorize this deviation?"*

---

## 8. Core Philosophy & Engineering Principles

Fable 2.0 is built on the engineering philosophy extracted from the **ADK 2.0 Beta (v2.0.0-beta.1)** commit history:

1.  **Deterministic Orchestration over Prompt-Based Routing:** Replace "black-box" routing with explicit Graph-Based Workflows (`c25d86f1`).
2.  **State Reconstruction over JSON Injection:** Utilize event-based state reconstruction (`ca327329`) for native resumability. State is never passed as a string; it is reconstructed by the ADK `SessionService`.
3.  **Execution Isolation:** Rely on `NodeRunner` isolation (`0b3e7043`) to ensure a failure in a Research Node doesn't crash the Storyteller.

---

## 9. Implementation Roadmap

1.  **Phase 1: Pure State Model** (DONE)
2.  **Phase 2: GraphRAG Infrastructure** (DONE)
3.  **Phase 3: Node Configuration** (DONE)
4.  **Phase 4: Workflow Orchestration** (DONE)
5.  **Phase 5: World Simulation Boot** (DONE)
6.  **Phase 6: Server & WebSocket Integration** (DONE)
7.  **Phase 7: Productionization & Advanced Telemetry** (DONE)
8.  **Phase 8: Advanced Dynamic Initialization & Research Swarm** (DONE)
9.  **Phase 9: Narrative Intelligence & Long-Term Continuity** (DONE)
10. **Phase 10: Narrative Guardrails & Context Sanitization** (DONE)
11. **Phase 11: The Rewrite Feature** (DONE)
    *   Expose native `rewind_async` functionality to the UI.
    *   Inject [SYSTEM REWRITE CONSTRAINT] via `new_message` to steer Storyteller.
12. **Phase 12: Enhanced Suspicion Engine** (DONE)
    *   Semantic "Secret Proximity" detection via local Ollama embeddings + cosine similarity (`>0.78`).
    *   "Suspicion Protocol" preamble injected via `before_model_callback` (not `before_agent_callback` — that hook *replaces* agent output instead of steering it; an early implementation tripped this and Phase 12 silently never fired).
    *   `ChoiceGenerator` emits `{prompt, choices: [{text, tier}]}` with `tier ∈ {null, oblivious, uneasy, suspicious, breakthrough}`; UI renders tier-coded buttons (slate / amber / orange / rose-pulse).
13. **Phase 13: ADK 2.0 Native Alignment & UI State Surface** (DONE)
    *   Replaced reinvented plugins with ADK's bundled `GlobalInstructionPlugin` + `LoggingPlugin`.
    *   Attached `state_schema=FableAgentState`; consumers use `ctx.state.to_dict()` instead of private `_value`/`_delta`.
    *   Public `google.adk.workflow` imports; `recovery_node` reachable; auditor retry counter (`temp:audit_retries`).
    *   New `state_update` WS event surfaces strain, cast, divergences, mood, chapter, location, timeline_date.
    *   `update_relationship` persists significant trust shifts (`|trust_delta| >= 20`) as `LoreEdge` rows with `visibility_whitelist=[PROTAGONIST, target]`.
    *   `commit_lore` and `report_violation` tools complete the 6-tool belt.
    *   Lore ingestion: `asyncio.gather` parallel embeddings + per-batch SQL commits.

---

## 10. Verification Status

This plan historically over-promised on what was "verified." Below is the honest map of what's been probed end-to-end vs. implemented but unprobed:

| Claim | Status | Notes |
|---|---|---|
| Workflow graph constructs (20 nodes, `state_schema=FableAgentState`) | ✅ Probed | Smoke test imports `build_fable_workflow()` and asserts node count + schema attachment. |
| Compaction summarizer doesn't crash on `Workflow` root | ✅ Probed | Explicit `LlmEventSummarizer(llm=Gemini(...))` passed; no fallback to the broken `_ensure_compaction_summarizer`. |
| Archivist has `PlanReActPlanner` + `mode='ANY'` + 6 tools | ✅ Probed | Smoke test asserts all three. |
| `state_update` WS payload matches contract | ✅ Probed | Frontend discriminated union + `assertNever` exhaustiveness check. |
| Suspicion plugin actually fires when similarity > 0.78 | ⚠️ Implemented, unprobed end-to-end | Hook + state-access bugs fixed; no automated test asserts the LLM receives the "SUSPICION PROTOCOL" preamble on a controlled input. |
| Epistemic filter active in `search_memory` | ⚠️ Implemented, unprobed | Code path exists; no integration test confirms forbidden concepts are dropped from retrieval. |
| `LoreEdge` upserts on significant trust shifts | ⚠️ Implemented, unprobed | Code present; no test asserts a row appears in `lore_edges`. |
| Recovery routing after 3 auditor failures | ⚠️ Implemented, unprobed | Counter logic exists; no test forces 3 failures end-to-end. |
| Lore ingestion parallel batches survive Ollama 503 | ⚠️ Implemented, unprobed | `return_exceptions=True` in place; no chaos test. |
| HITL `rerun_on_resume=True` survives RequestInput round-trip | ⚠️ Implemented, unprobed | Decorator set; no test exercises a full setup-resume cycle. |
| GEPA prompt optimization | ❌ Not implemented | See §6.A. |
| `ReflectAndRetryToolPlugin` | ❌ Not implemented | See §6.B. |

**Convention:** ✅ = at least one programmatic probe asserts the claim; ⚠️ = code in place, looks correct, no automated test exercising it; ❌ = not built.

**Honest reading:** ~30% of the architecture is verified end-to-end; ~60% is implemented-but-unprobed; ~10% is aspirational. The next investment that pays off most is a `tests/` smoke harness with one integration test per ⚠️ row.

---

## Conclusion
By leveraging ADK 2.0's deterministic graphs, node isolation, memory services, and native telemetry, Fable 2.0 is a next-generation **simulation-grade narrative engine**. Phases 1–13 are implemented and end-to-end smoke-tested at the import level; advanced ADK Beta features (GEPA, `ReflectAndRetryToolPlugin`) remain aspirational and are tagged as such above. See §10 for the verification map separating probed claims from implemented-but-unprobed ones.