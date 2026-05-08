# Changelog

All notable changes to Fable 2.0. Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [v2.1 — V1 Vision Alignment: Living Bible + Literary Prose] — 2026-05-08

A staged port of the FableWeaver v1 prose-quality bar onto the v2 ADK 2.0 graph.
Each phase is independently shippable; together they take the engine from
"generic 400-word AI chapters" to "v1-spec 4-8k word literary fanfiction with a
living World Bible substrate."

### Phase A — Storyteller prose quality port

- New phased storyteller instruction (Phase 0 Bible consultation -> 1 canonical
  faithfulness -> 2 chapter structure with HARD RULES (4-8k words, first char
  `#`, three-layer opening, power-with-limit beats, anti-Worfing) -> 3 timeline
  integration -> 4 prose+fenced JSON output).
- `src/state/chapter_output.py`: Pydantic `ChapterOutput` model
  (summary / choices / timeline / canon_elements_used / power_limitations_shown
  / stakes_tracking / character_voices_used / questions) plus
  `parse_chapter_tail` helper.
- Storyteller keeps `tools=[lore_lookup]` + `before_model_callback`; max_output_tokens=24576.
- New `FableAgentState.last_chapter_meta` carries the parsed dict.

### Phase B — Typed choice taxonomy + meta-questions

- `choice_generator` LlmAgent removed (redundant — storyteller already emits
  typed choices in its JSON tail). Replaced with `user_choice_input_node`
  reading `state.last_chapter_meta`.
- Auditor becomes the canonical parser: splits prose vs JSON tail, audits
  prose only, writes `last_story_text=prose` and
  `last_chapter_meta=ChapterOutput.model_dump()`.
- 4-tier choice taxonomy on the frontend: canon (emerald) / divergence
  (amber) / character (indigo) / wildcard (rose, with a pulse).
- Meta-questions panel: 1-2 questions per chapter shape the next chapter's
  tone/style; submit gated until all answered.

### Phase C — Living World Bible substrate

- 7 new state fields modelling the v1-aligned substrate: `canon_timeline`
  (events with pressure / tier / playbook / status retirement),
  `character_voices`, `power_origins` (techniques with cost + limitations),
  `stakes_and_consequences` (costs_paid / near_misses / power_usage_debt /
  pending_consequences with due_by_chapter), `knowledge_boundaries`,
  `canon_character_integrity` (anti-Worf floors), `identities`
  (multi-persona graph).
- `LoreKeeperOutput` grew from 3 to 9 fields populated on initial setup.
- 6 new archivist tools (`update_character_voice`, `add_pending_consequence`,
  `materialize_butterfly_effect`, `advance_event_status`,
  `mark_knowledge_violation`, `mark_power_scaling_violation`). 12 total.
- Storyteller `before_model_callback` builds 6 enforcement blocks per turn
  (TIMELINE / VOICES / POWER SYSTEM / PROTECTED / STAKES LEDGER / KNOWLEDGE
  BOUNDARIES) plus the GraphRAG "Known facts" block. Per-turn idempotent
  pending-consequence overdue tick.

### Phase D — Multi-turn setup wizard

- Single-turn wizard step inserted between lore_dump and configuration.
- Direct `google.genai` call generates ONE laser-focused clarifying question
  targeting power-fusion mechanics, character identity, timeline anchor, or
  isolation strategy — never vague flavor.
- `state.setup_conversation` persisted as a list of `{role, content}`
  entries; the planner_input embeds it as HARD CREATIVE DIRECTION.
- Frontend SetupWizard grows from 3-step to 4-step indicator (adds Refine).
  New `setup_wizard_question` HITL render branch with option pills + "Other"
  free-text escape hatch.

### Phase E — Transactional rewrite with original-chapter reference

- `runner.rewind_async` already rolls back state via computed deltas, but it
  cannot recover the deleted chapter's prose. Phase E captures
  `last_story_text` + last 3 `chapter_summaries` + `chapter_count` BEFORE
  rewind and feeds them into the rewrite turn as reference context.
- Rewrite message now spells out: SAME chapter number, same plot beats, do
  not write a different chapter, do not acknowledge the instruction in
  prose. Original chapter included (truncated) as "DO NOT copy verbatim".

### Phase F — Targeted on-demand research tool

- `trigger_research(topic)` storyteller tool: single direct Gemini call with
  `Tool(google_search=GoogleSearch())` grounding, synthesises a 1-2 paragraph
  summary, persists it as a `LoreEmbedding` row so future turns can retrieve
  via `lore_lookup`.
- Rate-limited to 2 calls per chapter via
  `state['temp:research_calls_this_chapter']`; auditor resets the counter on
  AUDIT PASSED.

### Phase G — Source-universe leakage guard

- `src/utils/leakage_terms.py`: per-universe term lists (jjk, worm, marvel,
  mahouka, naruto, dragonball) with universe-title aliases and substring
  fallback.
- `detect_leakage(text, story_universes)` returns hits with surrounding
  context. Auditor runs it on AUDIT PASSED and appends hits to
  `violation_log` as soft warnings; never blocks the chapter.

## [Phase 13 — ADK 2.0 Native Alignment & UI State Surface] — 2026-05-08

Audit-and-fix sweep across ~25 ADK 2.0 alignment issues plus closure of the backend→UI coverage gap (UI surface went from ~45% to ~85%). Commit: `1441709`.

### Fixed (Critical — Phase 12 actually fires now)
- **`SuspicionPlugin` was silently broken.** Used `before_agent_callback` returning `Content` (which *replaces* agent output instead of steering it) and accessed `callback_context.context.state` (`AttributeError` swallowed by a bare `except`). Phase 12 had likely never fired before this fix. Now uses `before_model_callback` and mutates `llm_request.config.system_instruction`.
- **`GlobalInstructionPlugin` reinvented an ADK-bundled plugin.** Replaced with `from google.adk.plugins.global_instruction_plugin import GlobalInstructionPlugin` + an `InstructionProvider` callable.
- **`Workflow(sub_nodes=[...])` was not a real kwarg.** Silently dropped by Pydantic — `recovery_node` was therefore unreachable. Now wired via the auditor's `"recovery"` route after 3 consecutive failures.
- **HITL nodes missing `rerun_on_resume=True`.** Added on `fallback_injector` and `inject_lore_to_state` — branching logic now re-evaluates after `RequestInput` resume.
- **Runtime `NameError`s** in `lore_keeper.py` and `summarizer.py` (used `RequestInput`/`Event`/`EventActions`/`FableAgentState`/`types` before importing them).
- **`EventsCompactionConfig` would crash on first compaction trigger** because `_ensure_compaction_summarizer` requires an `LlmAgent` root and Fable's root is a `Workflow`. Now passes an explicit `LlmEventSummarizer(llm=Gemini(...))`.
- **`_epistemic_graph_filter` was dead code** — `search_memory` returned the global corpus regardless of `forbidden_concepts`. Filter now active.
- **Archivist had no planner attached** and the plan referenced a fictitious `tool_choice='any'` kwarg. Now uses `PlanReActPlanner()` + `FunctionCallingConfig(mode='ANY')`.

### Fixed (High)
- State extraction switched from private `state._value | state._delta` to public `ctx.state.to_dict()` across 7+ sites.
- `event.get_function_calls()` replaces fictitious `actions.tool_calls` reads. Tool-call status messages now actually fire.
- Removed manual `invocation_id` per turn (defeated ADK resume); pulled from `event.invocation_id` for `turn_complete`.
- Streaming gated on `event.partial` / `event.is_final_response()` to avoid replaying chunks.
- Narrowed broad `except Exception` in runner: re-raises `CancelledError`, distinct `NodeTimeoutError` handling, `logger.exception` on residual.
- `forbidden_concepts` enforcement now two-layer (graph filter + auditor substring fallback).
- `TelemetryPlugin` switched to dict-based event-sourced state mutation; bare `except` removed.

### Added (Backend)
- New `state_update` WebSocket event emitted before `turn_complete` carrying `power_debt_level`, `active_characters`, `active_divergences`, `timeline_date`, `location`, `mood`, `chapter`.
- `commit_lore` and `report_violation` archivist tools (completing the 6-tool belt).
- `LoreEdge` GraphRAG sync: `update_relationship` upserts edges with source `PROTAGONIST` and `visibility_whitelist=[PROTAGONIST, target]` on `|trust_delta| >= 20`.
- `state_schema=FableAgentState` attached to the workflow; `violation_log` field added to the model.
- Auditor retry counter (`temp:audit_retries`) routes to `recovery_node` after 3 consecutive failures.
- `recovery_node → choice_generator_agent_node` edge so the player can redirect after a graceful degradation.
- Lore ingestion: `asyncio.gather` parallel embeddings + per-batch SQL commits (resilient to individual Ollama failures).

### Added (Frontend — closing the ~45% backend coverage gap)
- 4-tier suspicion choice rendering: **slate** (oblivious) / **amber** (uneasy) / **orange** (suspicious) / **rose** with framer-motion glow pulse (breakthrough).
- **Strain bar** in `StoryView` header — pulses red when level `>80`.
- **Sidebar tabs:** Lore Stream / Cast / Divergences with empty states.
- **Header info row:** chapter / `timeline_date` / location / mood.
- **Inline framer-motion rewrite modal** replaces `window.prompt()`. Quick-pick chips: "darker", "more action", "more dialogue", "less expository".
- Discriminated union over WebSocket message types with `assertNever` exhaustiveness check.
- Exponential-backoff reconnect (1s → 2s → 4s → 8s → 16s, max 5 attempts).
- `VITE_API_BASE` / `VITE_WS_BASE` env vars; defaults to `localhost:8001`.
- `text_delta.author` honored — narrator vs. system styling.
- `Undo2` icon replaces semantically-wrong `ServerCrash` for the undo button.

### Changed
- `FableLocalMemoryService` (Postgres + pgvector + Ollama) replaces planned `VertexAiRagMemoryService` — local stack chosen for offline-first dev. Migration to Vertex remains trivial because the `BaseMemoryService` interface is matched.
- Public ADK imports (`from google.adk.workflow import FunctionNode, JoinNode, START`) replace private underscored imports where alternatives exist. `_workflow_hitl_utils` and `_workflow_graph_utils.build_node` retained with `# noqa` and explanatory comments — no public alternatives in ADK 2.0 Beta.

### Known Limitations
- `tests/` directory does not exist; ~60% of architectural claims are implemented-but-unprobed end-to-end. See [`FABLE_2_0_PLAN.md`](FABLE_2_0_PLAN.md) §10 for the verification matrix.
- GEPA prompt optimization (planned §6.A) — not implemented.
- `ReflectAndRetryToolPlugin` (planned §6.B) — not implemented.
- `_workflow_hitl_utils` and `_workflow_graph_utils.build_node` private-API imports remain; no public alternative exists in ADK 2.0 Beta. Upstream issue should be filed against `google/adk-python`.

---

For prior phase history, see `FABLE_2_0_PLAN.md` §9 (Implementation Roadmap).
