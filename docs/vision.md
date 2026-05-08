# Fable 2.0 Vision (v2.1: V1 Alignment)

This document captures the prose-quality and substrate targets the v2.1
release aligns the engine to. It pairs with `CHANGELOG.md` Phase A–G
entries; this doc is the *why*, the changelog is the *what*.

## Reading-experience targets

The engine should produce **published-quality crossover fanfiction**, not
short AI chat responses. Concrete targets:

- **Chapter length**: 4,000–8,000 words per turn. The current model
  (`gemini-3.1-flash-lite-preview`) tends to undershoot; instruction +
  `max_output_tokens=24576` give it room. Word count is a guideline, not
  a hard validator.
- **Chapter format**: every chapter begins literally with `# Chapter N`
  (markdown header) — first output character must be `#`. No preamble,
  no acknowledgements of instructions, no "I will now…".
- **Three-layer opening rhythm**: paragraph 1 sensory grounding,
  paragraph 2 universe-specific lore, paragraph 3 character interiority.
  See `/tmp/v1_dump/kageaki_ch1.md` (in the v1 repo) for the canonical
  example.
- **Power AND its cost in the same beat**: every named technique appears
  bound by its limitation in the same scene. "He used Infinity to deflect
  the blow" is wrong; "He used Infinity to deflect the blow, the
  vomit-rag taste of his last spirit ingestion still coating his throat"
  is right.
- **Specificity from the Bible**: "four thousand three hundred and
  twenty-seven independent wills" not "thousands". Numbers, names, and
  techniques live in `state.power_origins` / `active_characters`, and the
  prompt's per-turn enforcement blocks surface them so the prose can
  drop them as throwaway specificity.
- **4 typed choices + 1-2 meta-questions**: every chapter ends with one
  CANON / DIVERGENCE / CHARACTER / WILDCARD choice tied to a named
  upcoming canon event, plus 1-2 meta-questions that shape the next
  chapter's tone/style.

## The 16 business needs

These are the v1 properties Fable 2.0 v2.1 reproduces:

1. Published-quality fanfiction prose — long-form, three-layer openings,
   power-with-limit beats, canon density, sensory grounding.
2. Living World Bible substrate — 12+ top-level fields growing 5-10 KB
   per chapter; the storyteller has rich context to reference.
3. Multi-turn setup wizard — `setup_conversation` USER↔AI dialogue
   persisted as hard creative direction; AI asks ONE laser-focused
   fusion-mechanic question.
4. Typed/hooked choices + meta-questions — 4 typed choices each tied to
   a named upcoming canon event; 1-2 meta-questions for tone/style.
5. Stakes loop (no effortless wins) — every chapter records
   `power_limitations_shown[]`, `costs_paid[]`, `near_misses[]`,
   `power_debt_incurred{}`, `consequences_triggered[]`. Even non-combat
   chapters track narrative costs.
6. Canon timeline pressure — events tagged MANDATORY/HIGH/MEDIUM,
   `[!!!]` MUST appear; events retire on occurred/modified/prevented.
7. Character voice fidelity — per-character speech_patterns,
   vocabulary_level, verbal_tics, topics_to_avoid.
8. Anti-Worfing — protected characters with `minimum_competence` floors.
9. Multi-identity tracking — civilian/hero/vigilante personas with
   `known_by`, `suspected_by`, `linked_to` graphs (state field exists;
   archivist update tooling deferred to a follow-up).
10. Knowledge boundaries — per-character forbidden concepts; archivist
    flags `knowledge_violation` when a character references something
    they shouldn't know.
11. Source-universe leakage detection — auto-flags "Cursed Energy" in a
    non-JJK story.
12. Rewrite as transactional rollback — Bible state snapshotted
    pre-chapter via ADK's `rewind_async`, original chapter shown to the
    model as reference, user's modifier applied; same chapter number.
13. Targeted on-demand research — single-hunter `trigger_research(topic)`
    tool the storyteller can call mid-chapter; not a 10-hunter swarm.
14. OC power-source-aware research — query_planner gets
    `setup_conversation` + a hint to research NAMED canon characters
    mentioned as power sources (e.g. "Gojo's powers" → research Gojo).
15. In-world time progression — chapter_start_date / chapter_end_date /
    time_elapsed per chapter (in `ChapterOutput.timeline`).
16. `# Chapter X` header convention — first output character must be `#`.

## Architecture map (v2.1)

```
START
  │
  └─► world_builder ─(lore_dump → wizard → config → complete)─────────────┐
                                                                          │
                                                                          ▼
                                              query_planner ──► query_parser
                                                                          │
                                                                          ▼
                                                            lore_hunter swarm  (×10 parallel)
                                                                          │
                                                                          ▼
                                                                   swarm_join
                                                                          │
                                                                          ▼
                                                         lore_keeper (LlmAgent)
                                                                          │
                                                                          ▼
                                                          inject_lore_to_state
                                                                          │
                                              (HITL: setup_world_primer)──┘
                                                                          │
                                                                          ▼
       ┌──────────────────► intent_router ──┬─► storyteller ──► auditor ──┐
       │                                    │                              │
       │                                    └─► query_planner (research)  │
       │                                                                  │
       │   ┌───────────────────────── archivist ◄──────(passed)───────────┘
       │   │
       │   ▼
       │  summarizer (LlmAgent → parser)
       │   │
       │   ▼
       │  user_choice_input_node ──(HITL: user_choice_selection)
       │   │
       └───┘
```

## What's deferred

- Source-text auto-enrichment of canon event playbooks (v1 pre-loaded
  rich beats from book/wiki source as events approached).
- Multi-identity update tools on the archivist (state schema is in
  place; tooling to add/modify identities mid-chapter is a follow-up).
- Auto-rewriting on leakage detection (current behavior: log + UI flag,
  rewrites stay user-initiated).
