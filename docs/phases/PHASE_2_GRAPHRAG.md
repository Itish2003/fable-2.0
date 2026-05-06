# Phase 2: Local GraphRAG Infrastructure & Primary Source ETL

## 1. Objective
Replace the flat V1 JSON context injection with a highly scalable, **Local Knowledge Graph** (GraphRAG) inspired by the `code-review-mcp` architecture. This phase implements the ETL pipeline to ingest massive Light Novel manuscripts and establishes the "Epistemic Filtering" logic using **Ollama** for local embeddings and **Postgres** for storage.

## 2. Core local Primitives
*   **Ollama**: Local embedding engine (running `mxbai-embed-large` or similar).
*   **NetworkX**: Python graph library for narrative relationship traversal.
*   **pgvector**: Postgres extension for high-performance local vector storage.
*   `google.adk.memory.BaseMemoryService`: Custom implementation (`FableLocalMemoryService`).

## 3. Technical Architecture

### A. The "Code-Review" Pattern for Lore
Just as `code-review-mcp` maps code dependencies, Fable 2.0 maps narrative dependencies:
*   **Nodes:** Characters, Locations, Factions, Canon Events.
*   **Edges:** "Allied_With", "Located_In", "Knows_Secret", "Parent_Of".
*   **Storage:** We will use a `LoreNode` table in Postgres for metadata and a `LoreEmbedding` table (pgvector) for semantic chunks of the Light Novels.

### B. The LoreIngestionNode (ETL)
*   **Input:** Raw Light Novel manuscripts (Vols 1-8).
*   **Processing:** Chunks text semantically. For each chunk, it calls the local **Ollama API** to generate embeddings.
*   **Indexing:** Saves chunks to Postgres, linking them to their corresponding Graph Nodes (e.g., a paragraph about 'Tatsuya' is linked to the 'Tatsuya' Character Node).

### C. Epistemic Filtering (Radius Traversal)
When the `StorytellerNode` needs context:
1.  **Entry Point:** Find the node for the current location or POV character.
2.  **Graph Traversal:** Use NetworkX to find all nodes within a radius of 1 or 2 edges.
3.  **Epistemic Filter:** Check edge weights for "Visibility". If an edge represents a secret the POV character doesn't know, the traversal blocks that path.
4.  **Injection:** Only the semantic chunks linked to the *visible* subgraph are injected into the prompt.

## 4. Step-by-Step Implementation

1.  **Setup Local Environment:**
    *   Enable `pgvector` in the local Postgres database.
    *   Initialize the `ollama` Python client.
2.  **Implement `FableLocalMemoryService`:**
    *   Create `src/services/memory_service.py` inheriting from `BaseMemoryService`.
    *   Implement `search_memory` to perform a hybrid Search (Vector Similarity + Graph Traversal).
3.  **Build the ETL Worker:**
    *   Implement `src/nodes/lore_ingestion.py`.
    *   Integrate your legacy PyPDF/Playwright logic to feed this new pipeline.
4.  **NetworkX Integration:**
    *   Build a service to sync the Postgres Lore tables into an in-memory NetworkX graph for fast traversal.

## 5. Validation Criteria
*   [x] Ollama successfully generates embeddings for a sample paragraph locally.
*   [x] Postgres successfully stores and retrieves vectors using `pgvector`.
*   [x] A query for "First High" correctly pulls only the visible characters and locations connected in the graph.
