# Phase 1: Pure State Model & Session Continuity

## 1. Objective
Establish the foundational data structures for Fable 2.0. This phase replaces the monolithic, brittle `world_bible.json` payload with a strictly typed Pydantic `AgentState`. It also initializes the ADK 2.0 `DatabaseSessionService` to enable native session persistence and zero-logic narrative branching.

## 2. Core ADK 2.0 Primitives
*   `google.adk.agents.BaseAgentState`: The base class for our Pydantic state model.
*   `google.adk.sessions.DatabaseSessionService`: ADK 2.0's native PostgreSQL session manager.
*   `pydantic.Field`: For strict schema validation and LLM instruction enforcement.

## 3. Technical Architecture

### A. The `FableAgentState` Model
Unlike V1, which passed the entire lore to the LLM, the `FableAgentState` only tracks *mutable, narrative-critical state variables* that change rapidly from turn to turn. Deep lore remains in the GraphRAG (Phase 2).

```python
class CharacterState(BaseModel):
    trust_level: int = Field(ge=-100, le=100)
    dynamic_tags: list[str] = Field(description="Current emotional/status tags (e.g., 'suspicious', 'exhausted')")

class FableAgentState(BaseAgentState):
    power_debt: int = Field(default=0, description="Strain level of the protagonist. >80 triggers exhaustion penalties.")
    timeline_date: str = Field(description="Current in-world date/time.")
    active_characters: dict[str, CharacterState] = Field(description="Characters currently in the scene.")
    active_divergences: list[str] = Field(description="Active butterfly effects altering canon.")
```

### B. The Session Service
*   Instead of custom SQLAlchemy models for `History` and `Story`, we will configure the ADK `DatabaseSessionService`.
*   **Branching API:** To implement the `/family-tree` and `/branch` features, we will utilize the `parent_session_id` parameter when creating a new session.

## 4. Step-by-Step Implementation

1.  **Initialize Database Schema:**
    *   Configure SQLAlchemy async engine for PostgreSQL.
    *   Run ADK 2.0's built-in initialization script to generate the required session, events, and state tables.
2.  **Define Pydantic Models:**
    *   Create `src/state/models.py`.
    *   Implement `FableAgentState` ensuring all fields use `Field(description="...")` to guide the LLM.
3.  **Implement Session Wrappers:**
    *   Create `src/services/session_manager.py`.
    *   Wrap `DatabaseSessionService` to handle Fable-specific branching (e.g., creating a branch directly from event `$N`).

## 5. Validation Criteria
*   [x] Pydantic models validate successfully without throwing `ValidationError`.
*   [x] Starting a new session successfully commits the default `FableAgentState` to Postgres.
*   [x] Branching a session successfully carries over the `AgentState` from the parent checkpoint.
