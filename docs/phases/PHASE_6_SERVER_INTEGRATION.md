# Phase 6: Server & WebSocket Integration

## 1. Objective
Connect the isolated ADK 2.0 Graph Workflow to the outside world. This phase involves setting up the FastAPI application, establishing the WebSocket endpoints, and building the asynchronous execution loop that translates ADK 2.0 `Event` objects into client-facing WebSocket messages.

## 2. Core ADK 2.0 Primitives
*   `google.adk.apps.app.App`: The declarative container for our graph, plugins, and services.
*   `google.adk.runners.Runner` (or `Workflow._run_impl`): The engine that executes the graph and yields events.
*   `google.adk.events.event.Event`: The standard output object from the LLM nodes.
*   `google.adk.events.request_input.RequestInput`: The suspension object for the WorldBuilder setup wizard.

## 3. Technical Architecture

### A. The FastAPI App (`src/main.py`)
*   Initializes the `DatabaseSessionService` and `VertexAiRagMemoryService` (or our local equivalent) on startup.
*   Registers the ADK `App` container globally.
*   Exposes REST endpoints for creating sessions (`POST /stories`) and the WebSocket endpoint (`/ws/story/{session_id}`).

### B. The WebSocket Manager (`src/ws/manager.py`)
*   Maintains active connections.
*   Handles connection lifecycle (connect, disconnect, heartbeat).
*   Translates internal server errors into safe JSON payloads for the client.

### C. The Execution Loop (`src/ws/runner.py`)
This is the bridge between ADK 2.0 and the Frontend.
*   **Input Routing:** Receives JSON from the WebSocket. Checks if it's a command (e.g., `/rewrite`), a `RequestInput` reply, or a standard progression choice.
*   **The Generator:** Calls `runner.run_async(...)` and iterates over the yielded events using an `async for` loop.
*   **Event Filtering:**
    *   `isinstance(event, RequestInput)`: Sends a `{"type": "request_input", "message": "..."}` payload to the client and breaks the loop (suspending).
    *   `event.author == "storyteller"`: Extracts `event.content.parts[0].text` and streams it as `{"type": "text_delta"}`.
    *   `event.author == "archivist"`: Suppresses text, but watches for tool call events to send `{"type": "status", "message": "Updating lore..."}`.

## 4. Step-by-Step Implementation

1.  **Define the ADK App:**
    *   Create `src/app_container.py`. Instantiate the `App` object with our `fable_main_workflow` as the root node. Attach the database and memory services.
2.  **Build the Connection Manager:**
    *   Implement `src/ws/manager.py` with standard FastAPI WebSocket connection pooling.
3.  **Implement the Runner Loop:**
    *   Create `src/ws/runner.py`. Write the loop that consumes ADK events and formats them for the frontend.
4.  **Wire the Endpoints:**
    *   Create `src/main.py`. Register the routers and startup/shutdown lifecycles for database connection pooling.

## 5. Validation Criteria
*   [ ] FastAPI server starts without dependency or schema errors.
*   [ ] A test client can connect to the WebSocket and trigger the `WorldBuilderNode`.
*   [ ] The server successfully streams a `RequestInput` to the client, pauses, receives the reply, and resumes the graph execution.
*   [ ] The `StorytellerNode`'s generated text is successfully streamed back in chunks.
