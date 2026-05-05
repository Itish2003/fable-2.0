# Phase 2: GraphRAG Infrastructure & Primary Source ETL

## 1. Objective
Replace the flat V1 JSON context injection with a highly scalable, dynamically injected Knowledge Graph. This phase implements the ETL pipeline to ingest massive Light Novel manuscripts (Volumes 1-8) and establishes the "Epistemic Filtering" logic to prevent Soft Forbidden Knowledge leaks.

## 2. Core ADK 2.0 Primitives
*   `google.adk.memory.VertexAiRagMemoryService`: Native ADK 2.0 vector/graph retrieval engine.
*   `google.adk.workflow._base_node.BaseNode`: For creating the background ETL worker (`LoreIngestionNode`).

## 3. Technical Architecture

### A. The `LoreIngestionNode` (ETL)
Replaces the legacy `source_text.py`. 
*   Takes raw PDF/TXT files of Light Novels.
*   Chunks text using semantic boundaries (e.g., chapters, scene breaks).
*   Embeds chunks and pushes them into the `VertexAiRagMemoryService`.

### B. Epistemic Filtering (Graph Traversal)
Replaces `fk_detector.py`. 
*   **Structure:** Entities (Characters, Locations) are nodes. Relationships are edges.
*   **Edge Weights ("Visibility"):** Edges are tagged with permissions (e.g., `["Tatsuya", "Mayumi"]`).
*   **Traversal:** When querying the memory service, the GraphRAG traverses outward from the POV character. It drops any nodes connected via edges the POV character lacks permission to "see".

## 4. Step-by-Step Implementation

1.  **Setup Vertex AI Connections:**
    *   Configure GCP credentials and initialize the `VertexAiRagMemoryService`.
2.  **Build the ETL Worker:**
    *   Implement `src/nodes/lore_ingestion.py`.
    *   Write the chunking algorithm specifically tuned for Light Novel prose (retaining dialogue context).
3.  **Implement Epistemic Metadata:**
    *   Define metadata schemas for the Vector DB entries that include `known_by` arrays.
4.  **Create the Context Filter:**
    *   Write a retrieval function that accepts the `AgentState` (active characters) and queries the Memory Service, filtering out restricted lore before returning the string context.

## 5. Validation Criteria
*   [ ] ETL pipeline successfully chunks and uploads a 50k+ word LN volume without timing out.
*   [ ] A query for a specific character retrieves their description AND their immediate relationships (radius 1).
*   [ ] A query for a "Secret" returns empty if the requesting character is not in the `known_by` list (Epistemic Filter success).
