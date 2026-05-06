# Phase 5: World Simulation Boot Sequence

## 1. Objective
Replace the V1 REST API setup wizard (`/clarify`, `/refine`) with a native ADK 2.0 interactive Node. This phase establishes the initial `AgentState` before the main `FableWorkflow` ever begins, ensuring Chapter 1 is perfectly grounded.

## 2. Core ADK 2.0 Primitives
*   `google.adk.events.RequestInput`: Pauses agent execution to solicit human responses.
*   `google.adk.workflow._function_node.FunctionNode` or `LlmAgentWrapper`: To drive the conversational wizard.

## 3. Technical Architecture

### The `WorldBuilderNode`
*   Instead of jumping straight into prose generation, a new story invokes the `WorldBuilderNode`.
*   It operates in a `while` loop, asking the user questions (Genre, Tropes, Protagonist abilities).
*   It yields `RequestInput` events to the WebSocket, pausing execution until the user replies.
*   Once the user types `/confirm`, it compiles the answers, issues the initial Tool Calls to populate the `FableAgentState` (Phase 1), and initiates the background `LoreHunter` swarm (Phase 2) to prep the Vector DB.

## 4. Step-by-Step Implementation

1.  **Create the WorldBuilder Node:**
    *   Implement `src/nodes/world_builder.py`.
    *   Configure it with Gemini 1.5 Pro to handle fluid, conversational Q&A.
2.  **Implement RequestInput Logic:**
    *   Ensure the node correctly suspends state and emits `RequestInput` events to the frontend UI.
    *   Handle the resumption of the node when the WebSocket receives the user's reply.
3.  **State Initialization Handoff:**
    *   Once the setup conversation concludes, execute the logic to instantiate the initial `FableAgentState`.
    *   Trigger the `FableWorkflow` (Phase 4) with the newly populated state, seamlessly transitioning the user from "Setup Mode" to "Story Mode".

## 5. Validation Criteria
*   [x] The `WorldBuilderNode` successfully emits `RequestInput` events and suspends.
*   [x] User replies correctly resume the node's execution context.
*   [x] Completing the wizard successfully populates the `FableAgentState` and triggers the first node of the main `FableWorkflow`.
