import { randomUUID } from "node:crypto";
import { defineChannel, GET, POST } from "eve/channels";
import {
  AgentCard,
  type Message,
  Role,
  SendMessageRequest,
  SendMessageResponse,
} from "@a2a-js/sdk";

// A2A spec 1.0 inbound surface (notes/architecture.md §2 in the portfolio
// repo): the agent card at the IANA-registered well-known path, plus a
// JSON-RPC 2.0 endpoint handling SendMessage. Serialization goes through
// @a2a-js/sdk's generated codecs (proto3 JSON mapping) so any SDK client —
// including the portfolio's dynamic discovery tool — round-trips exactly.

const BASE_URL = process.env.A2A_BASE_URL ?? "http://localhost:2001";

const card: AgentCard = {
  name: "fable-2.0",
  description:
    "Project agent for Fable 2.0: a deterministic, event-sourced, simulation-grade interactive fiction engine on Google ADK 2.0 Beta. A typed DAG replaces prompt-chaining — the Storyteller writes prose, the Auditor checks it against canon and routes backward on hallucination, the Archivist mutates persistent state. Ask about its architecture, the Suspicion Engine, event-sourced rewind, or the parallel LoreHunter research swarm.",
  version: "2.1.0",
  supportedInterfaces: [
    {
      url: `${BASE_URL}/a2a`,
      protocolBinding: "JSONRPC",
      protocolVersion: "1.0",
      tenant: "",
    },
  ],
  provider: undefined,
  documentationUrl: "https://github.com/Itish2003/fable-2.0",
  capabilities: {
    streaming: false,
    pushNotifications: false,
    extensions: [
      {
        // Portfolio convention: a card can advertise a live, embeddable demo
        // of the project's own frontend. The portfolio renders whatever URL
        // the card declares — no project-specific code on the embedder side.
        uri: "urn:x-portfolio:live-demo",
        description:
          "Embeddable live frontend of this project (direct iframe; no frame-blocking headers).",
        required: false,
        params: { url: process.env.DEMO_URL ?? "http://localhost:5173" },
      },
    ],
    extendedAgentCard: false,
  },
  securitySchemes: {},
  securityRequirements: [],
  defaultInputModes: ["text/plain"],
  defaultOutputModes: ["text/plain"],
  skills: [
    {
      id: "explain-architecture",
      name: "Explain the engine architecture",
      description:
        "Explain how Fable 2.0 replaces prompt-chained AI Dungeon Masters with a strictly typed ADK Workflow DAG: Storyteller → Auditor → Archivist, with explicit backward routing when the Auditor catches prose that contradicts canon.",
      tags: ["architecture", "adk", "dag", "reliability", "hallucination"],
      examples: [
        "How does fable-2.0 handle model failure?",
        "What happens when the LLM hallucinates?",
      ],
      inputModes: [],
      outputModes: [],
      securityRequirements: [],
    },
    {
      id: "event-sourced-rewind",
      name: "Event-sourced timeline & undo",
      description:
        "Describe the immutable event ledger and how ADK's rewind_async() reconstructs the timeline to the exact millisecond before a mistake — undo as time travel, not state mutation.",
      tags: ["event-sourcing", "undo", "rewind", "postgres"],
      examples: ["How does undo work?", "What does event-sourced mean here?"],
      inputModes: [],
      outputModes: [],
      securityRequirements: [],
    },
    {
      id: "suspicion-engine",
      name: "Semantic Suspicion Engine",
      description:
        "Explain the dramatic-irony detector: pgvector cosine similarity between generated prose and hidden forbidden concepts (threshold 0.78) steers choice generation via before_model_callback into a 4-tier awareness spectrum (oblivious/uneasy/suspicious/breakthrough), rendered as slate/amber/orange/rose-pulse choices.",
      tags: ["embeddings", "pgvector", "ollama", "ux"],
      examples: ["What is the Suspicion Engine?"],
      inputModes: [],
      outputModes: [],
      securityRequirements: [],
    },
    {
      id: "lorehunter-swarm",
      name: "Parallel LoreHunter research swarm",
      description:
        "Describe how a crossover premise spawns parallel LoreHunter agents (ADK parallel_worker=True) that research and synthesize a rigid World Bible before Chapter 1.",
      tags: ["multi-agent", "parallel", "research"],
      examples: ["How does it handle crossover fanfiction?"],
      inputModes: [],
      outputModes: [],
      securityRequirements: [],
    },
  ],
  signatures: [],
};

// eve continuation token ↔ A2A contextId: both name a resumable conversation.
// A caller that echoes back the contextId we return resumes the same session.

type StreamEvent = { type: string; data?: Record<string, unknown> };

async function awaitTurnReply(
  stream: ReadableStream<StreamEvent>,
  sentText: string,
  timeoutMs = 180_000,
): Promise<string> {
  const reader = stream.getReader();
  const timer = setTimeout(() => void reader.cancel().catch(() => {}), timeoutMs);
  // A resumed session's stream replays history first. Our turn is the LAST
  // message.received whose text matches what we just sent; its turnId keys
  // the completion events we wait for.
  let turnId: string | undefined;
  let reply: string | undefined;

  try {
    for (;;) {
      const { done, value: event } = await reader.read();
      if (done) break;
      const data = (event.data ?? {}) as Record<string, unknown>;
      if (event.type === "message.received" && data.message === sentText) {
        turnId = data.turnId as string;
      } else if (
        event.type === "message.completed" &&
        turnId !== undefined &&
        data.turnId === turnId
      ) {
        reply = data.message as string;
      } else if (
        (event.type === "turn.completed" && data.turnId === turnId) ||
        event.type === "session.waiting"
      ) {
        if (reply !== undefined) return reply;
      } else if (event.type === "turn.failed" || event.type === "session.failed") {
        throw new Error(`agent turn failed: ${JSON.stringify(data).slice(0, 300)}`);
      }
    }
  } finally {
    clearTimeout(timer);
    await reader.cancel().catch(() => {});
  }
  if (reply !== undefined) return reply;
  throw new Error("timed out waiting for agent reply");
}

function rpcError(id: unknown, code: number, message: string, status = 200) {
  return Response.json(
    { jsonrpc: "2.0", id: id ?? null, error: { code, message } },
    { status },
  );
}

export default defineChannel({
  cors: true,
  routes: [
    // The spec path is /.well-known/agent-card.json, but a literal route
    // ending in ".json" breaks eve's build (nitro/rolldown parses the
    // generated route module as JSON because of the extension). Matching the
    // filename as a param keeps the extension out of the route pattern.
    GET("/.well-known/:file", async (_req, { params }) => {
      if (params.file !== "agent-card.json") {
        return new Response("not found", { status: 404 });
      }
      return Response.json(AgentCard.toJSON(card));
    }),

    POST("/a2a", async (req, { send }) => {
      let rpc: { jsonrpc?: string; id?: unknown; method?: string; params?: unknown };
      try {
        rpc = await req.json();
      } catch {
        return rpcError(null, -32700, "Parse error");
      }
      if (rpc.jsonrpc !== "2.0") {
        return rpcError(rpc.id, -32600, "Invalid Request: jsonrpc must be '2.0'");
      }
      if (rpc.method !== "SendMessage") {
        return rpcError(rpc.id, -32601, `Method not found: ${rpc.method}`);
      }

      let params: SendMessageRequest;
      try {
        params = SendMessageRequest.fromJSON(rpc.params);
      } catch {
        return rpcError(rpc.id, -32602, "Invalid params");
      }
      const text = (params.message?.parts ?? [])
        .map((p) => (p.content?.$case === "text" ? p.content.value : ""))
        .filter(Boolean)
        .join("\n");
      if (!text) {
        return rpcError(rpc.id, -32602, "Invalid params: no text parts in message");
      }

      const contextId = params.message?.contextId || randomUUID();
      const session = await send(text, {
        auth: null,
        continuationToken: contextId,
      });
      const replyText = await awaitTurnReply(await session.getEventStream(), text);

      const reply: Message = {
        messageId: randomUUID(),
        contextId,
        taskId: "",
        role: Role.ROLE_AGENT,
        parts: [
          {
            content: { $case: "text", value: replyText },
            metadata: undefined,
            filename: "",
            mediaType: "",
          },
        ],
        metadata: undefined,
        extensions: [],
        referenceTaskIds: [],
      };
      return Response.json({
        jsonrpc: "2.0",
        id: rpc.id ?? null,
        result: SendMessageResponse.toJSON({
          payload: { $case: "message", value: reply },
        }),
      });
    }),
  ],
});
