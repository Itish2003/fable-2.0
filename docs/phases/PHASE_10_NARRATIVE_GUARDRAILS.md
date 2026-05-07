# Phase 10: Narrative Guardrails & Context Sanitization

## 1. Objective
Port the final advanced LLM guardrails from the legacy V1 implementation into the ADK 2.0 framework. This phase focuses on preventing "Context Leakage" (cross-universe terminology bleed), enforcing strict "Power Scale" rules to prevent the LLM from artificially nerfing protagonists, and adding a programmatic fallback for tool-calling failures.

## 2. Core ADK 2.0 Primitives
*   `AgentPlugin.before_agent_callback`: Used to dynamically inject aggressive Power Scale instructions into the Storyteller's context window before text generation.
*   `google.adk.workflow.FunctionNode`: For the Fallback Extraction routing.
*   **Pure Python String Manipulation**: For the Anti-Leakage Regex scrubber inside the `LoreKeeper` node tools.

## 3. Technical Architecture

### A. Context Anti-Leakage System
When the `LoreHunterSwarm` scrapes wikis, the text is contaminated with source-universe jargon (e.g., "Chakra", "Cursed Energy"). If injected raw, the Storyteller will hallucinate this jargon into the current story universe.
*   **Implementation:** Port V1's `_remove_universe_terms` dictionary logic into a `sanitize_text()` helper function.
*   **Execution:** The `LoreKeeper` tools must pass all scraped descriptions through this sanitizer before mutating `ctx.state`.

### B. Dynamic Power Scale Enforcement (Anti-Nerf)
LLMs have a strong bias toward "balanced" storytelling, often making continental-level protagonists struggle against street-level thugs to create artificial tension.
*   **Implementation:** Update `src/plugins/global_instruction.py`.
*   **Execution:** Read `ctx.state.get("power_level")`. If the level is `continental` or `planetary`, prepend the aggressive V1 Anti-Nerf prompt: *"DEMONSTRATE FULL POWER AT SCALE. DO NOT artificially limit power..."*

### C. Programmatic Fallback Extraction
LLMs occasionally fail to emit structured tool calls during complex reasoning tasks, resulting in lost research data.
*   **Implementation:** Add a `FallbackExtractorNode` to the graph.
*   **Execution:** If the `LoreKeeper` finishes but `ctx.state` was not mutated, the graph routes to the Fallback Extractor, which uses a strict, low-temperature prompt to force-extract the JSON from the raw Swarm text dump.

### D. The 'Enrich' Auto-Analyzer
The World Bible decays in quality as the story progresses.
*   **Implementation:** A scheduled or manually triggered `EnrichAnalyzerNode`.
*   **Execution:** Scans `ctx.state` for gaps (e.g., "Character X has no disposition"). If found, it routes back to the `QueryPlannerNode` mid-story to patch the hole.

## 4. Step-by-Step Implementation

1.  **Implement the Sanitizer:**
    *   Create `src/utils/sanitizer.py`.
    *   Port the V1 leakage dictionary (JJK, Worm, Naruto terms -> Generic terms).
2.  **Update Global Instructions:**
    *   Modify `src/plugins/global_instruction.py` to include the Power Scale logic.
3.  **Implement Fallback Routing:**
    *   Update `src/nodes/lore_keeper.py` to check for mutations.
    *   Create `src/nodes/fallback_extractor.py`.
    *   Update `src/graph/workflow.py` with the fallback edge logic.
4.  **Implement Enrich Mechanics:**
    *   Build the `enrich_analyzer_node`.
    *   Add a UI button to trigger an "Enrich" WebSocket event.

## 5. Validation Criteria
*   [ ] The word "Chakra" scraped from a Naruto wiki is automatically replaced with "energy" before saving to `ctx.state`.
*   [ ] Selecting the "Continental" power level successfully injects the "CRITICAL POWER LEVEL GUIDANCE" into the Storyteller's prompt.
*   [ ] If the `LoreKeeper` LLM fails to call its tools, the graph catches the failure and forces extraction via the `FallbackExtractorNode`.
*   [ ] Clicking "Enrich Bible" successfully identifies a missing data field and triggers the `LoreHunterSwarm` mid-story.
