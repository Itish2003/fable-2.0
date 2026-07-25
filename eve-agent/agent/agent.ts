import { defineAgent } from "eve";
import { createOpenAICompatible } from "@ai-sdk/openai-compatible";

// Default: DeepSeek's OpenAI-compatible API (deepseek-v4-flash — probed
// 2026-07-25; key from DEEPSEEK_API_KEY). Any OpenAI-compatible endpoint
// works via env: the friend's Ollama box was MODEL_BASE_URL=
// http://192.168.1.12:11434/v1 MODEL_ID=gemma4:12b (no key needed).
const provider = createOpenAICompatible({
  name: "project-model",
  baseURL: process.env.MODEL_BASE_URL ?? "https://api.deepseek.com/v1",
  apiKey: process.env.MODEL_API_KEY ?? process.env.DEEPSEEK_API_KEY,
});

export default defineAgent({
  model: provider(process.env.MODEL_ID ?? "deepseek-v4-flash"),
  modelContextWindowTokens: Number(process.env.MODEL_CONTEXT_TOKENS ?? 131_072),
  // Both axes explicit per notes/architecture.md §5 — the defaults are
  // effectively uncapped. Now metered API spend, not a free local box.
  limits: {
    maxInputTokensPerSession: 1_000_000,
    maxOutputTokensPerSession: 100_000,
  },
});
