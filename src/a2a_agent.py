"""In-process A2A agent — fable-2.0's real project agent.

Mounts two routes (agent card + JSON-RPC SendMessage) directly onto the
fable-2.0 FastAPI engine's own app object (see src/main.py), in the same
uvicorn process. No Node, no eve, no subprocess: the agent brain is a plain
httpx chat loop with a two-tier model fallback, and its grounding tools call
the engine on localhost (same process, same event loop). Promoted from the
in-process experiment (formerly src/a2a_inprocess.py + src/main_inprocess.py,
2026-07-25); eve-agent/ remains in the repo as the retired Node reference.

Wire format: parts:[{"text": "..."}] on both request and reply — verified
against the real @a2a-js/sdk codec (a text part's proto3-JSON wire form IS
{"text": ...}; the TS reference's `$case` wrapper is only the SDK's
in-memory shape after `fromJSON` deserializes this same JSON).
"""

import json
import logging
import os
import uuid
from typing import Any

import httpx
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

logger = logging.getLogger("fable.a2a_agent")

A2A_BASE_URL = os.getenv("A2A_BASE_URL", "http://localhost:8001")
DEMO_URL = os.getenv("DEMO_URL", "http://localhost:5173")

CARD: dict[str, Any] = {
    "name": "fable-2.0",
    "description": (
        "Project agent for Fable 2.0: a deterministic, event-sourced, "
        "simulation-grade interactive fiction engine on Google ADK 2.0 Beta. "
        "A typed DAG replaces prompt-chaining — the Storyteller writes prose, "
        "the Auditor checks it against canon and routes backward on "
        "hallucination, the Archivist mutates persistent state. Ask about "
        "its architecture, the Suspicion Engine, event-sourced rewind, or "
        "the parallel LoreHunter research swarm."
    ),
    "version": "2.1.0",
    "supportedInterfaces": [
        {
            "url": f"{A2A_BASE_URL}/a2a",
            "protocolBinding": "JSONRPC",
            "protocolVersion": "1.0",
            "tenant": "",
        }
    ],
    "documentationUrl": "https://github.com/Itish2003/fable-2.0",
    "capabilities": {
        "streaming": False,
        "pushNotifications": False,
        "extensions": [
            {
                "uri": "urn:x-portfolio:live-demo",
                "description": (
                    "Embeddable live frontend of this project (direct "
                    "iframe; no frame-blocking headers)."
                ),
                "required": False,
                "params": {"url": DEMO_URL},
            },
        ],
        "extendedAgentCard": False,
    },
    "securitySchemes": {},
    "securityRequirements": [],
    "defaultInputModes": ["text/plain"],
    "defaultOutputModes": ["text/plain"],
    "skills": [
        {
            "id": "explain-architecture",
            "name": "Explain the engine architecture",
            "description": (
                "Explain how Fable 2.0 replaces prompt-chained AI Dungeon "
                "Masters with a strictly typed ADK Workflow DAG: Storyteller "
                "→ Auditor → Archivist, with explicit backward routing when "
                "the Auditor catches prose that contradicts canon."
            ),
            "tags": ["architecture", "adk", "dag", "reliability", "hallucination"],
            "examples": [
                "How does fable-2.0 handle model failure?",
                "What happens when the LLM hallucinates?",
            ],
            "inputModes": [],
            "outputModes": [],
            "securityRequirements": [],
        },
        {
            "id": "event-sourced-rewind",
            "name": "Event-sourced timeline & undo",
            "description": (
                "Describe the immutable event ledger and how ADK's "
                "rewind_async() reconstructs the timeline to the exact "
                "millisecond before a mistake — undo as time travel, not "
                "state mutation."
            ),
            "tags": ["event-sourcing", "undo", "rewind", "postgres"],
            "examples": ["How does undo work?", "What does event-sourced mean here?"],
            "inputModes": [],
            "outputModes": [],
            "securityRequirements": [],
        },
        {
            "id": "suspicion-engine",
            "name": "Semantic Suspicion Engine",
            "description": (
                "Explain the dramatic-irony detector: pgvector cosine "
                "similarity between generated prose and hidden forbidden "
                "concepts (threshold 0.78) steers choice generation via "
                "before_model_callback into a 4-tier awareness spectrum "
                "(oblivious/uneasy/suspicious/breakthrough), rendered as "
                "slate/amber/orange/rose-pulse choices."
            ),
            "tags": ["embeddings", "pgvector", "ollama", "ux"],
            "examples": ["What is the Suspicion Engine?"],
            "inputModes": [],
            "outputModes": [],
            "securityRequirements": [],
        },
        {
            "id": "lorehunter-swarm",
            "name": "Parallel LoreHunter research swarm",
            "description": (
                "Describe how a crossover premise spawns parallel "
                "LoreHunter agents (ADK parallel_worker=True) that research "
                "and synthesize a rigid World Bible before Chapter 1."
            ),
            "tags": ["multi-agent", "parallel", "research"],
            "examples": ["How does it handle crossover fanfiction?"],
            "inputModes": [],
            "outputModes": [],
            "securityRequirements": [],
        },
    ],
    "signatures": [],
}

# ---------------------------------------------------------------------------
# Model chain: primary local endpoint, DeepSeek fallback on infra failure.
# Mirrors /Users/itish/workspace/portfolio/agent/agent.ts semantics.
# ---------------------------------------------------------------------------

MODEL_PRESET = os.getenv("MODEL_PRESET", "local")
LOCAL_BASE_URL = os.getenv("LOCAL_MODEL_BASE_URL", "https://metres-permit-thumbs-procedure.trycloudflare.com/v1")
LOCAL_MODEL_ID = "gemma4:12b"
DEEPSEEK_BASE_URL = "https://api.deepseek.com/v1"
DEEPSEEK_MODEL_ID = "deepseek-v4-flash"
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")

SYSTEM_PROMPT = """You are the fable-2.0 project agent — the dedicated agent \
for one project in Itish Srivastava's portfolio.

Fable 2.0 is a deterministic, event-sourced, simulation-grade interactive \
fiction engine built on Google ADK 2.0 Beta. Control flow is a typed DAG: \
the Storyteller writes prose, the Auditor checks it against canon and routes \
backward on hallucination, the Archivist mutates persistent state. The \
database is an immutable event ledger; undo uses ADK's rewind_async() to \
reconstruct the timeline to the exact millisecond before a mistake. The \
Suspicion Engine uses pgvector cosine similarity (threshold 0.78) between \
generated prose and hidden forbidden concepts to steer choices into a \
4-tier awareness spectrum. A crossover premise spawns parallel LoreHunter \
agents to research a World Bible before Chapter 1.

You have two tools that reach the real, live engine on this same process: \
engine_status and list_stories. Use them before claiming the engine is \
running or describing its API — check, don't recite. Keep replies short \
and skimmable. Never fabricate features or metrics. Stay on fable-2.0."""

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "engine_status",
            "description": (
                "Check whether the Fable 2.0 engine is live right now and "
                "report its API surface from the auto-generated OpenAPI spec."
            ),
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_stories",
            "description": (
                "List story sessions persisted in the live engine for one "
                "user (real state from the event-sourced Postgres ledger)."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "user_id": {
                        "type": "string",
                        "description": "User whose stories to list.",
                        "default": "local_tester",
                    }
                },
            },
        },
    },
]

ENGINE_ORIGIN = os.getenv("ENGINE_ORIGIN", "http://127.0.0.1:8001")


async def _tool_engine_status(args: dict[str, Any]) -> dict[str, Any]:
    del args  # takes no parameters; kept for uniform TOOL_IMPLS dispatch
    try:
        async with httpx.AsyncClient(timeout=4.0) as client:
            res = await client.get(f"{ENGINE_ORIGIN}/openapi.json")
        if res.status_code != 200:
            return {"live": False, "note": f"engine answered HTTP {res.status_code}"}
        spec = res.json()
        operations = [
            f"{m.upper()} {p} ({op.get('operationId', '?')})"
            for p, methods in (spec.get("paths") or {}).items()
            for m, op in methods.items()
        ]
        return {
            "live": True,
            "title": (spec.get("info") or {}).get("title"),
            "version": (spec.get("info") or {}).get("version"),
            "operations": operations,
        }
    except Exception as e:
        return {"live": False, "note": f"engine offline: {e}"}


async def _tool_list_stories(args: dict[str, Any]) -> dict[str, Any]:
    user_id = args.get("user_id") or "local_tester"
    try:
        async with httpx.AsyncClient(timeout=6.0) as client:
            res = await client.get(f"{ENGINE_ORIGIN}/stories/{user_id}")
        if res.status_code != 200:
            return {"live": False, "note": f"engine answered HTTP {res.status_code}"}
        body = res.json()
        stories = body.get("stories", body)
        return {"live": True, "count": len(stories) if isinstance(stories, list) else None, "stories": stories}
    except Exception as e:
        return {"live": False, "note": f"engine offline: {e}"}


TOOL_IMPLS = {"engine_status": _tool_engine_status, "list_stories": _tool_list_stories}


def _is_infra_error(exc: Exception) -> bool:
    if isinstance(exc, httpx.HTTPStatusError) and getattr(exc, "response", None) is not None:
        return exc.response.status_code >= 500
    # Connection errors, timeouts, DNS failures: never reached the provider.
    return True


async def _chat_once(client: httpx.AsyncClient, base_url: str, model: str, api_key: str | None, messages: list[dict]) -> dict:
    headers = {"content-type": "application/json"}
    if api_key:
        headers["authorization"] = f"Bearer {api_key}"
    payload = {"model": model, "messages": messages, "tools": TOOLS, "tool_choice": "auto"}
    res = await client.post(f"{base_url}/chat/completions", json=payload, headers=headers, timeout=60.0)
    if res.status_code >= 400:
        logger.error("chat completion %s error body: %s", res.status_code, res.text[:2000])
    res.raise_for_status()
    return res.json()


async def run_agent_turn(history: list[dict[str, str]]) -> str:
    """history: list of {"role": "user"|"assistant", "content": str}."""
    messages: list[dict[str, Any]] = [{"role": "system", "content": SYSTEM_PROMPT}, *history]

    async with httpx.AsyncClient() as client:
        for _ in range(4):  # cap tool-call round trips
            try:
                data = await _chat_once(client, LOCAL_BASE_URL, LOCAL_MODEL_ID, None, messages)
            except Exception as err:
                if not _is_infra_error(err):
                    raise
                logger.warning(
                    "model chain: %s unreachable (%s), degrading to %s",
                    LOCAL_MODEL_ID, err, DEEPSEEK_MODEL_ID,
                )
                if not DEEPSEEK_API_KEY:
                    return "The primary model is unreachable and no fallback API key is configured."
                data = await _chat_once(client, DEEPSEEK_BASE_URL, DEEPSEEK_MODEL_ID, DEEPSEEK_API_KEY, messages)

            choice = data["choices"][0]["message"]
            tool_calls = choice.get("tool_calls")
            if not tool_calls:
                return choice.get("content") or ""

            # Providers attach non-standard extra fields to "thinking" output
            # (DeepSeek: reasoning_content, others: reasoning). Replaying one
            # provider's extra field back to a DIFFERENT provider on fallback
            # breaks that provider's own thinking-mode validation (probed
            # 2026-07-25: DeepSeek 400s on a history entry carrying a local
            # model's "reasoning" field instead of its own "reasoning_content").
            # Keep only the standard OpenAI chat fields in history.
            messages.append(
                {
                    "role": choice.get("role", "assistant"),
                    "content": choice.get("content") or "",
                    "tool_calls": tool_calls,
                }
            )
            for tc in tool_calls:
                name = tc["function"]["name"]
                try:
                    args = json.loads(tc["function"].get("arguments") or "{}")
                except Exception:
                    args = {}
                impl = TOOL_IMPLS.get(name)
                result = await impl(args) if impl else {"error": f"unknown tool {name}"}
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc["id"],
                        "content": json.dumps(result),
                    }
                )
        return "Reached the tool-call round limit without a final answer."


# ---------------------------------------------------------------------------
# Per-context conversation history (in-memory).
# ---------------------------------------------------------------------------

CONTEXT_HISTORY: dict[str, list[dict[str, str]]] = {}

router = APIRouter()


@router.get("/.well-known/agent-card.json")
async def agent_card():
    return JSONResponse(CARD)


def _rpc_error(rpc_id: Any, code: int, message: str) -> JSONResponse:
    return JSONResponse({"jsonrpc": "2.0", "id": rpc_id, "error": {"code": code, "message": message}})


@router.post("/a2a")
async def a2a_send_message(request: Request):
    try:
        rpc = await request.json()
    except Exception:
        return _rpc_error(None, -32700, "Parse error")

    rpc_id = rpc.get("id")
    if rpc.get("jsonrpc") != "2.0":
        return _rpc_error(rpc_id, -32600, "Invalid Request: jsonrpc must be '2.0'")
    if rpc.get("method") != "SendMessage":
        return _rpc_error(rpc_id, -32601, f"Method not found: {rpc.get('method')}")

    params = rpc.get("params") or {}
    message = params.get("message") or {}
    parts = message.get("parts") or []
    text = "\n".join(p.get("text", "") for p in parts if p.get("text")).strip()
    if not text:
        return _rpc_error(rpc_id, -32602, "Invalid params: no text parts in message")

    context_id = message.get("contextId") or str(uuid.uuid4())
    history = CONTEXT_HISTORY.setdefault(context_id, [])
    history.append({"role": "user", "content": text})

    try:
        reply_text = await run_agent_turn(history)
    except Exception as e:
        logger.exception("agent turn failed")
        return _rpc_error(rpc_id, -32603, f"agent turn failed: {e}")

    history.append({"role": "assistant", "content": reply_text})

    reply = {
        "messageId": str(uuid.uuid4()),
        "contextId": context_id,
        "taskId": "",
        "role": "ROLE_AGENT",
        "parts": [{"text": reply_text}],
    }
    return JSONResponse({"jsonrpc": "2.0", "id": rpc_id, "result": {"message": reply}})
