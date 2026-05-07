# Prompting Strategy: The V2 Paradigm Shift

Fable 2.0 represents a fundamental shift in how we instruct LLMs. We have moved away from legacy "Super Prompts" (which suffered from context dilution and instruction ignoring) to a **Dynamic Prompt Assembly** model natively supported by the Google ADK 2.0 framework.

## 1. Separation of Concerns (Micro-Agents)
In V1, a single agent tried to write the story, format JSON, update states, and maintain character voices all at once. In V2, cognitive load is distributed across specialized nodes:
*   **QueryPlannerNode**: Strictly outputs JSON arrays for research targeting.
*   **StorytellerNode**: Has one job—write rich, immersive, lore-accurate prose based on the World Bible. It does not call tools.
*   **ArchivistNode**: Never writes prose. It only reads the output and executes tools to mutate `ctx.state`.
*   **ChoiceGeneratorNode**: Reads the story and strictly generates 4 interactive choices.

## 2. Dynamic Injection ("Hot State" Prompting)
Instead of hardcoding a massive set of rules that apply to every turn, Fable 2.0 uses **ADK Plugins (`before_agent_callback`)** to inject hyper-specific micro-prompts exactly when they are needed. These instructions exist only for the relevant turn and are cleared immediately.
*   **Dynamic Power Scales**: If `ctx.state["power_level"] == "continental"`, the `GlobalInstructionPlugin` injects an aggressive "Anti-Nerf" prompt: *"DEMONSTRATE FULL POWER AT SCALE. DO NOT artificially limit power..."*
*   **Strain Modulation**: If `power_debt > 80`, the plugin injects pacing notes: *"CRITICAL OVERRIDE: The protagonist is severely exhausted..."*
*   **Rewrite Constraints**: If the user clicks "Rewrite" with the instruction "Make it darker," the WebSocket runner dynamically injects `[SYSTEM REWRITE CONSTRAINT: Make it darker]` directly into the Storyteller's `new_message` context.

## 3. Semantic Suspicion Engine
V1 used basic keyword extraction to guess if a character was near a secret. V2 uses the `SuspicionPlugin` to run real-time **Cosine Similarity** math (via local Ollama `pgvector` embeddings) against `ctx.state["forbidden_concepts"]`.
If the mathematical tension is high, the plugin dynamically rewrites the `ChoiceGenerator` instructions to force the "Awareness Spectrum" (Oblivious -> Breakthrough). The engine understands subtext without hardcoded keyword begging.

## 4. Elimination of "JSON Begging"
In V1, prompts dedicated paragraphs to begging the model to output valid JSON (`OUTPUT STRICTLY VALID JSON. DO NOT USE MARKDOWN.`).
In V2, we leverage the Gemini API's native structured outputs via ADK 2.0:
```python
generate_content_config=types.GenerateContentConfig(
    response_schema=WorldBibleExtraction,
    response_mime_type="application/json"
)
```
This physically constrains the LLM to output perfect Pydantic-compliant JSON, making our `FallbackExtractor` and `LoreKeeper` nodes virtually bulletproof and freeing up prompt tokens for narrative depth.

## 5. Epistemic Shielding (Post-Generation Validation)
In V1, prompts tried to prevent knowledge leakage ("Do not let the character know X"). By placing "X" in the prompt, the LLM inevitably hallucinated it.
In V2, the **AuditorNode** (a pure Python function) acts as a firewall. It checks the text *after* generation. If the Storyteller accidentally leaks a forbidden concept, the Auditor yields a `failed` route, throwing the graph backward to rewrite the scene. The prompt is structurally enforced by code, not by instruction begging.
