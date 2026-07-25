import { defineTool } from "eve/tools";
import { z } from "zod";

const API = process.env.FABLE_API_URL ?? "http://localhost:8001";

export default defineTool({
  description:
    "Check whether the Fable 2.0 engine (FastAPI backend) is live right now, and report its API surface from the auto-generated OpenAPI spec. Use before claiming the engine is running, and when a visitor asks what the live API exposes.",
  inputSchema: z.object({}),
  async execute() {
    try {
      const res = await fetch(`${API}/openapi.json`, {
        signal: AbortSignal.timeout(4_000),
      });
      if (!res.ok) return { live: false, note: `engine answered HTTP ${res.status}` };
      const spec = (await res.json()) as {
        info?: { title?: string; version?: string };
        paths?: Record<string, Record<string, { operationId?: string }>>;
      };
      const operations = Object.entries(spec.paths ?? {}).flatMap(
        ([p, methods]) =>
          Object.entries(methods).map(
            ([m, op]) => `${m.toUpperCase()} ${p} (${op.operationId ?? "?"})`,
          ),
      );
      return {
        live: true,
        title: spec.info?.title,
        version: spec.info?.version,
        operations,
      };
    } catch {
      return {
        live: false,
        note: "engine offline — it runs locally (uvicorn on :8001) and is not always up",
      };
    }
  },
});
