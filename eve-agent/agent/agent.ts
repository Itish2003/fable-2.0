import { defineAgent } from "eve";
import { createOpenAICompatible } from "@ai-sdk/openai-compatible";

// Model selection is one env var: MODEL_PRESET=local|deepseek (default
// local — the friend's Ollama box; deepseek is the metered fallback).
// Individual MODEL_BASE_URL / MODEL_ID / MODEL_API_KEY / MODEL_CONTEXT_TOKENS
// still override any preset field, so nothing is locked in.
const PRESETS = {
  local: {
    // Friend's Ollama box (probed 2026-07-25: gemma4:12b tool-calling
    // capable, 262k context, no key).
    baseURL: "http://192.168.1.12:11434/v1",
    modelId: "gemma4:12b",
    apiKey: () => undefined as string | undefined,
    contextTokens: 262_144,
  },
  deepseek: {
    baseURL: "https://api.deepseek.com/v1",
    modelId: "deepseek-v4-flash",
    apiKey: () => process.env.DEEPSEEK_API_KEY,
    contextTokens: 131_072,
  },
} as const;

const preset =
  PRESETS[(process.env.MODEL_PRESET ?? "local") as keyof typeof PRESETS] ??
  PRESETS.local;

const provider = createOpenAICompatible({
  name: "project-model",
  baseURL: process.env.MODEL_BASE_URL ?? preset.baseURL,
  apiKey: process.env.MODEL_API_KEY ?? preset.apiKey(),
});

export default defineAgent({
  model: provider(process.env.MODEL_ID ?? preset.modelId),
  modelContextWindowTokens: Number(
    process.env.MODEL_CONTEXT_TOKENS ?? preset.contextTokens,
  ),
  // Both axes explicit per notes/architecture.md §5 — the defaults are
  // effectively uncapped.
  limits: {
    maxInputTokensPerSession: 1_000_000,
    maxOutputTokensPerSession: 100_000,
  },
});
