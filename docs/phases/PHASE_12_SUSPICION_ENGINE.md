# Phase 12: Enhanced Suspicion Engine

## 1. Objective
Restore and significantly enhance the V1 "Forbidden Knowledge Detector" capability. This phase implements a semantic "Secret Proximity" system that detects when a protagonist is narratively near a forbidden concept using embeddings. It then forces the choice generator to provide options on an "Awareness Spectrum" (Oblivious to Breakthrough).

## 2. Core ADK 2.0 Primitives
*   `AgentPlugin.before_agent_callback`: Used to dynamically inject the "Suspicion Protocol" instructions and the specific detected secret into the Choice Generator's context.
*   `ctx.state`: To store and retrieve `forbidden_concepts` and recent scene embeddings.
*   `embedding_service`: Our local Ollama integration for semantic similarity math.

## 3. Technical Architecture

### A. Semantic Proximity Detection
Instead of V1's keyword matching, we will use vector math to detect tension.
*   **Workflow:** After the Storyteller generates a chapter, the system generates an embedding for the text.
*   **Math:** It calculates the cosine similarity between the chapter embedding and the embeddings of all `forbidden_concepts` currently in `ctx.state`.
*   **Trigger:** If similarity exceeds a threshold (e.g., > 0.8), the **Suspicion Protocol** is flagged in the state.

### B. The Awareness Spectrum Choices
If the protocol is active, the `ChoiceGenerator` agent is instructed to abandon generic choices and follow a strict 4-tier spectrum:
1.  **Level 1: Oblivious** (Protagonist ignores the clue entirely).
2.  **Level 2: Unease** (Protagonist feels something is wrong but lacks evidence).
3.  **Level 3: Suspicious** (Protagonist actively investigates or confronts the clue).
4.  **Level 4: Breakthrough** (Protagonist attempts a direct revelation, risking timeline instability).

### C. ADK 2.0 Integration
*   Implement a `SuspicionPlugin` that performs the math and modifies the `ChoiceGenerator` instructions.
*   Update `src/nodes/choice_generator.py` to handle the spectrum-style JSON output.

## 4. Step-by-Step Implementation

1.  **Update State Model:**
    *   Ensure `forbidden_concepts` in `FableAgentState` can support pre-calculated embeddings or calculate them on the fly.
2.  **Implement Suspicion Math:**
    *   Create a utility to compare the latest prose against the secret list.
3.  **Create Suspicion Plugin:**
    *   Implement the `before_agent_callback` for the choice generator.
4.  **Update Choice Generator Instruction:**
    *   Modify the agent's base system instruction to handle the "Suspicion Protocol" override.

## 5. Validation Criteria
*   [ ] A chapter mentioning "a mysterious monocle" (without using the word "Amon") correctly triggers a similarity match against the "Amon's True Identity" secret.
*   [ ] When triggered, the UI displays choices that explicitly follow the Oblivious -> Breakthrough spectrum.
*   [ ] The "Breakthrough" choice correctly leads to a narrative divergence in the next Storyteller turn.
