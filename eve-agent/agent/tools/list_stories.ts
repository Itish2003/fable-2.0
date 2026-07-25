import { defineTool } from "eve/tools";
import { z } from "zod";

const API = process.env.FABLE_API_URL ?? "http://localhost:8001";

export default defineTool({
  description:
    "List the story sessions persisted in the live Fable 2.0 engine for one user (GET /stories/{user_id} — read-only). Each row is real state from the event-sourced Postgres ledger: session, chapter, location, mood, premise. Use when a visitor asks what's running or wants proof the engine is real. Returns live:false if the engine is offline.",
  inputSchema: z.object({
    user_id: z
      .string()
      .default("local_tester")
      .describe(
        "User whose stories to list. The local dev frontend uses 'local_tester'.",
      ),
  }),
  async execute({ user_id }) {
    try {
      const res = await fetch(
        `${API}/stories/${encodeURIComponent(user_id)}`,
        {
          signal: AbortSignal.timeout(6_000),
        },
      );
      if (!res.ok) return { live: false, note: `engine answered HTTP ${res.status}` };
      const stories = await res.json();
      return { live: true, count: Array.isArray(stories) ? stories.length : null, stories };
    } catch {
      return {
        live: false,
        note: "engine offline — it runs locally (uvicorn on :8001) and is not always up",
      };
    }
  },
});
