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

Two methods on POST /a2a:

  SendMessage           blocking, one JSON response. Unchanged; this is
                        what production serves today.
  SendStreamingMessage  the same turn as SSE, gated behind
                        A2A_STREAMING_ENABLED (default off — see the
                        constant below for why it ships off).

SSE frame contract (SendStreamingMessage). Content-Type text/event-stream;
every `data:` line is one complete JSON-RPC response envelope:

  data: {"jsonrpc":"2.0","id":<id>,"result":{
           "message":{"messageId","contextId","taskId":"","role":"ROLE_AGENT",
                      "parts":[<one part>]},
           "final":false}}

`final` lives at the RESULT level, not inside the message. Parts are
distinguished by mediaType, the same convention the live-session
extension already uses:

  no mediaType                                     → answer text delta
  text/x-portfolio-reasoning                       → thinking delta, render
                                                     collapsed, never as answer
  application/x-portfolio-live-session+json        → session pointer (final frame)

Exactly one terminal frame is always sent: either `result.final: true`
(carrying the live-session part if a demo tool ran) or an `error`
envelope — an error frame is always terminal. Clients must not rely on
connection close. `: keep-alive` comments go out during long tool awaits
so intermediaries don't reap a silent stream.

Client note: this is a POST, so the browser side must be fetch() +
ReadableStream. EventSource cannot POST.
"""

import asyncio
import contextvars
import json
import logging
import os
import uuid
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any, NamedTuple

import httpx
from fastapi import APIRouter, Request
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, StreamingResponse

import src.demo_tools as demo_tools
import src.handback as handback
from src.spend_guard import check_spend, client_ip, record_usage

logger = logging.getLogger("fable.a2a_agent")

STATIC_DIR = Path(__file__).parent / "static"

A2A_BASE_URL = os.getenv("A2A_BASE_URL", "http://localhost:8001")

# One switch drives BOTH the card's capabilities.streaming and the method
# dispatch, so the card can never advertise a contract the deploy won't
# honour. Ships OFF: whether Vercel's Python runtime streams an ASGI
# response body incrementally or buffers it to completion is the single
# fact that decides the flip, and it cannot be established without
# deploying. Verify on the real deployment first (curl -N against
# /a2a, timestamping frames as they arrive); flip only if frames land
# incrementally rather than in one flush. A card that lies about
# streaming is worse than one that honestly says false.
STREAMING_ENABLED = os.getenv("A2A_STREAMING_ENABLED", "0").lower() in ("1", "true", "yes")

REASONING_MEDIA_TYPE = "text/x-portfolio-reasoning"
LIVE_SESSION_MEDIA_TYPE = "application/x-portfolio-live-session+json"
# Long tool awaits (an engine turn is the whole Storyteller→Auditor→
# Archivist DAG) would otherwise sit silent long enough for an
# intermediary to reap the connection.
SSE_KEEPALIVE_SECONDS = 15.0
# Same origin as the engine now (src/main.py mounts frontend/dist at /demo)
# instead of the separate `vite dev` origin the experiment card pointed at.
DEMO_URL = os.getenv("DEMO_URL", f"{A2A_BASE_URL}/demo/")

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
    "version": "2.2.0",
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
        "streaming": STREAMING_ENABLED,
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
            {
                "uri": "urn:x-portfolio:live-session",
                "description": (
                    "When a demo tool creates or advances a real engine "
                    "session, the reply carries an extra part (mediaType "
                    "application/x-portfolio-live-session+json) pointing "
                    "at that session: {sessionId, url, note}. The url is "
                    "a deep link into the live-demo iframe that opens the "
                    "exact session the agent just acted on."
                ),
                "required": False,
                "params": {},
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

# Declared only when streaming is on: the reasoning part exists solely
# inside an SSE stream, so advertising it while SendStreamingMessage is
# disabled would promise a contract the deploy cannot honour.
if STREAMING_ENABLED:
    CARD["capabilities"]["extensions"].append(
        {
            "uri": "urn:x-portfolio:reasoning-parts",
            "description": (
                "Inside a SendStreamingMessage stream, thinking/reasoning "
                f"arrives as parts with mediaType {REASONING_MEDIA_TYPE}, "
                "distinguishable from the answer's own text deltas (which "
                "carry no mediaType). Render it collapsed, never as answer "
                "prose."
            ),
            "required": False,
            "params": {"mediaType": REASONING_MEDIA_TYPE},
        }
    )

# ---------------------------------------------------------------------------
# Model chain: primary local endpoint, DeepSeek fallback on infra failure.
# Mirrors /Users/itish/workspace/portfolio/agent/agent.ts semantics.
# ---------------------------------------------------------------------------

MODEL_PRESET = os.getenv("MODEL_PRESET", "local")
# No default: an ephemeral tunnel URL baked in here would go stale the
# moment the tunnel restarts. Prod sets LOCAL_MODEL_BASE_URL explicitly;
# when it's unset the local attempt is skipped (see run_agent_turn below).
LOCAL_BASE_URL = os.getenv("LOCAL_MODEL_BASE_URL")
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
running or describing its API — check, don't recite.

You can also RUN the engine live for a visitor, not just describe it: \
start_demo_story creates a real story session and opens it in the \
visitor's live-demo iframe; advance_demo_story submits the next input \
(premise, setup answer, or chapter choice) and runs one real engine turn; \
rewind_demo_story undoes the most recent turn. Each of these is a real, \
metered model call (the Storyteller/Auditor/Archivist graph, not one \
call), so this conversation has a small budget of engine turns — don't \
call these tools speculatively, only when the visitor actually wants to \
see the engine run or asks you to advance/undo the demo. After using one, \
tell the visitor what happened in plain language; the session pointer is \
handled separately, you don't need to paste a URL yourself.

You own ONE project. When the visitor asks about a DIFFERENT project, asks \
what else Itish has built, or asks for a comparison you cannot ground in \
this repo, call ask_portfolio — the portfolio root agent knows the whole \
portfolio and routes to the right project agent. You must NOT answer from \
general knowledge about a project you do not own; say you're checking with \
the root agent, then relay what it says and credit it. If ask_portfolio \
comes back with handed_back false, tell the visitor to ask the root agent \
in the chat above — do not improvise an answer. Never call ask_portfolio \
for a question about fable-2.0 itself, and never call it twice in one \
conversation.

Keep replies short and skimmable. Never fabricate features or metrics. \
Stay on fable-2.0."""

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
    {
        "type": "function",
        "function": {
            "name": "start_demo_story",
            "description": (
                "Create a NEW live demo story session on the real engine and open it in "
                "the visitor's live-demo iframe. Use when a visitor wants to see the "
                f"engine actually run. Limited to {demo_tools.MAX_ENGINE_TURNS_PER_CONTEXT} "
                "engine turns per conversation -- don't call this more than once unless the "
                "visitor explicitly asks to restart."
            ),
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "advance_demo_story",
            "description": (
                "Submit the next input to the CURRENTLY OPEN demo story (a premise, a "
                "setup answer, or a chapter choice) and run one real engine turn. Call "
                "start_demo_story first if no demo story is open yet in this conversation. "
                f"Counts against the same {demo_tools.MAX_ENGINE_TURNS_PER_CONTEXT}-turn "
                "engine-turn budget shared with start_demo_story and rewind_demo_story for "
                "this conversation."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "input": {
                        "type": "string",
                        "description": "The premise, setup answer, or chapter choice text to submit.",
                    },
                    "session_id": {
                        "type": "string",
                        "description": "Optional -- defaults to the most recently started demo session in this conversation.",
                    },
                },
                "required": ["input"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "rewind_demo_story",
            "description": (
                "Undo the most recent turn of the currently open demo story (like the UI's "
                "Undo button). Counts against the same "
                f"{demo_tools.MAX_ENGINE_TURNS_PER_CONTEXT}-turn engine-turn budget shared "
                "with start_demo_story and advance_demo_story for this conversation."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "session_id": {
                        "type": "string",
                        "description": "Optional -- defaults to the most recently started demo session in this conversation.",
                    },
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "ask_portfolio",
            "description": (
                "Ask the portfolio ROOT agent a question this agent cannot ground in "
                "the fable-2.0 repo: another one of Itish's projects, what else he has "
                "built, or a cross-project comparison. The root agent routes to the "
                "project agent that actually owns the answer. Use this instead of "
                "answering from general knowledge about a project you do not own. Each "
                "call is at least two nested model turns and is limited to one per "
                "conversation -- never use it for fable-2.0 questions."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "question": {
                        "type": "string",
                        "description": "The visitor's question, phrased for an agent that knows the whole portfolio.",
                    }
                },
                "required": ["question"],
            },
        },
    },
]

ENGINE_ORIGIN = os.getenv("ENGINE_ORIGIN", "http://127.0.0.1:8001")
# Serverless platforms (Vercel) invoke the ASGI app in-process -- there is no
# loopback listener for the grounding tools to reach over real HTTP.
# ENGINE_TRANSPORT=asgi routes straight into the same app object via
# httpx.ASGITransport instead of a socket. VERCEL is set automatically by
# Vercel's build and runtime, so it's a sane default; the explicit var lets
# any future serverless host (or a compose test of this path) opt in without
# touching ENGINE_ORIGIN's meaning.
ENGINE_TRANSPORT = os.getenv("ENGINE_TRANSPORT", "asgi" if os.getenv("VERCEL") else "http")


def _engine_client(timeout: float) -> httpx.AsyncClient:
    if ENGINE_TRANSPORT == "asgi":
        # Deferred import: src/main.py imports this module to mount the
        # router, so importing src.main at module load time here would be
        # circular. By the time a tool actually runs, src.main has finished
        # importing and `app` exists in sys.modules.
        from src.main import app as engine_app

        return httpx.AsyncClient(
            transport=httpx.ASGITransport(app=engine_app), base_url="http://engine", timeout=timeout
        )
    return httpx.AsyncClient(base_url=ENGINE_ORIGIN, timeout=timeout)


async def _tool_engine_status(args: dict[str, Any]) -> dict[str, Any]:
    del args  # takes no parameters; kept for uniform TOOL_IMPLS dispatch
    try:
        async with _engine_client(4.0) as client:
            res = await client.get("/openapi.json")
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
        async with _engine_client(6.0) as client:
            res = await client.get(f"/stories/{user_id}")
        if res.status_code != 200:
            return {"live": False, "note": f"engine answered HTTP {res.status_code}"}
        body = res.json()
        stories = body.get("stories", body)
        return {"live": True, "count": len(stories) if isinstance(stories, list) else None, "stories": stories}
    except Exception as e:
        return {"live": False, "note": f"engine offline: {e}"}


TOOL_IMPLS = {
    "engine_status": _tool_engine_status,
    "list_stories": _tool_list_stories,
    "start_demo_story": demo_tools.start_demo_story,
    "advance_demo_story": demo_tools.advance_demo_story,
    "rewind_demo_story": demo_tools.rewind_demo_story,
    "ask_portfolio": handback.ask_portfolio,
}


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


class TurnResult(NamedTuple):
    reply: str
    input_tokens: int
    output_tokens: int


def _accumulate_usage(data: dict, usage: dict) -> None:
    u = data.get("usage") or {}
    usage["input_tokens"] += u.get("prompt_tokens", 0) or 0
    usage["output_tokens"] += u.get("completion_tokens", 0) or 0


async def run_agent_turn(history: list[dict[str, str]]) -> TurnResult:
    """history: list of {"role": "user"|"assistant", "content": str}."""
    messages: list[dict[str, Any]] = [{"role": "system", "content": SYSTEM_PROMPT}, *history]
    usage = {"input_tokens": 0, "output_tokens": 0}

    async with httpx.AsyncClient() as client:
        for _ in range(4):  # cap tool-call round trips
            if MODEL_PRESET == "deepseek":
                # Explicit override: skip the local attempt entirely (e.g. the
                # friend's box is known-busy) rather than paying its timeout
                # on every turn before degrading anyway.
                if not DEEPSEEK_API_KEY:
                    return TurnResult("MODEL_PRESET=deepseek but no DEEPSEEK_API_KEY is configured.", **usage)
                data = await _chat_once(client, DEEPSEEK_BASE_URL, DEEPSEEK_MODEL_ID, DEEPSEEK_API_KEY, messages)
            elif not LOCAL_BASE_URL:
                # No local endpoint configured -- skip straight to the fallback
                # instead of attempting a request with a missing base URL.
                if not DEEPSEEK_API_KEY:
                    return TurnResult("No local model endpoint is configured (LOCAL_MODEL_BASE_URL unset) and no fallback API key is configured.", **usage)
                data = await _chat_once(client, DEEPSEEK_BASE_URL, DEEPSEEK_MODEL_ID, DEEPSEEK_API_KEY, messages)
            else:
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
                        return TurnResult("The primary model is unreachable and no fallback API key is configured.", **usage)
                    data = await _chat_once(client, DEEPSEEK_BASE_URL, DEEPSEEK_MODEL_ID, DEEPSEEK_API_KEY, messages)

            _accumulate_usage(data, usage)
            choice = data["choices"][0]["message"]
            tool_calls = choice.get("tool_calls")
            if not tool_calls:
                return TurnResult(choice.get("content") or "", **usage)

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
        return TurnResult("Reached the tool-call round limit without a final answer.", **usage)


# ---------------------------------------------------------------------------
# Streaming turn. A deliberate parallel path, NOT a refactor of
# run_agent_turn: that function is what production serves today, and making
# it a consumer of a `stream: true` generator would make the working path
# depend on the local shim's streaming tool-call support — unknown, and not
# verifiable from a branch. The duplicated loop below is the cheaper risk
# while streaming ships gated off; unify once it's proven on the deploy.
# ---------------------------------------------------------------------------


def _stream_targets() -> tuple[list[tuple[str, str, str | None, bool]], str | None]:
    """The same model chain run_agent_turn walks, as an ordered list of
    (base_url, model, api_key, send_stream_options). Second element is a
    fatal message when nothing in the chain is usable.

    send_stream_options is False for the local shim on purpose: an unknown
    `stream_options` field would come back 4xx, and _is_infra_error treats
    4xx as non-infra, so it would hard-fail the turn instead of degrading.
    DeepSeek documents the field, and that's where the money is anyway;
    the local path falls back to an estimate.
    """
    deepseek = (DEEPSEEK_BASE_URL, DEEPSEEK_MODEL_ID, DEEPSEEK_API_KEY, True)
    if MODEL_PRESET == "deepseek":
        if not DEEPSEEK_API_KEY:
            return [], "MODEL_PRESET=deepseek but no DEEPSEEK_API_KEY is configured."
        return [deepseek], None
    if not LOCAL_BASE_URL:
        if not DEEPSEEK_API_KEY:
            return [], (
                "No local model endpoint is configured (LOCAL_MODEL_BASE_URL "
                "unset) and no fallback API key is configured."
            )
        return [deepseek], None
    local = (LOCAL_BASE_URL, LOCAL_MODEL_ID, None, False)
    return ([local, deepseek] if DEEPSEEK_API_KEY else [local]), None


def _estimate_tokens(text: str) -> int:
    """Only used when a provider streams without usage — the spend ledger
    undercounting silently is worse than a rough number."""
    return len(text) // 4


async def _chat_stream(
    client: httpx.AsyncClient,
    base_url: str,
    model: str,
    api_key: str | None,
    messages: list[dict],
    send_stream_options: bool,
) -> AsyncIterator[tuple[str, Any]]:
    """One streamed completion. Yields ("text", delta) / ("reasoning", delta)
    as they arrive, then exactly one ("message", assistant_message) and one
    ("usage", {"input_tokens", "output_tokens"})."""
    headers = {"content-type": "application/json", "accept": "text/event-stream"}
    if api_key:
        headers["authorization"] = f"Bearer {api_key}"
    payload: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "tools": TOOLS,
        "tool_choice": "auto",
        "stream": True,
    }
    if send_stream_options:
        payload["stream_options"] = {"include_usage": True}

    content: list[str] = []
    tool_acc: dict[int, dict[str, Any]] = {}
    usage: dict[str, int] | None = None

    async with client.stream(
        "POST", f"{base_url}/chat/completions", json=payload, headers=headers, timeout=120.0
    ) as res:
        if res.status_code >= 400:
            body = (await res.aread()).decode("utf-8", "replace")
            logger.error("chat completion %s error body: %s", res.status_code, body[:2000])
            res.raise_for_status()
        async for line in res.aiter_lines():
            if not line.startswith("data:"):
                continue
            raw = line[len("data:") :].strip()
            if not raw or raw == "[DONE]":
                continue
            try:
                chunk = json.loads(raw)
            except json.JSONDecodeError:
                continue
            u = chunk.get("usage") or {}
            if u:
                # Cumulative for the whole request, not per-chunk: assign.
                usage = {
                    "input_tokens": u.get("prompt_tokens", 0) or 0,
                    "output_tokens": u.get("completion_tokens", 0) or 0,
                }
            choices = chunk.get("choices") or []
            if not choices:
                continue
            delta = choices[0].get("delta") or {}
            # Providers disagree on the field name for thinking output
            # (DeepSeek: reasoning_content, others: reasoning) — same
            # divergence run_agent_turn documents when replaying history.
            for field in ("reasoning_content", "reasoning"):
                piece = delta.get(field)
                if piece:
                    yield "reasoning", piece
            piece = delta.get("content")
            if piece:
                content.append(piece)
                yield "text", piece
            for d in delta.get("tool_calls") or []:
                idx = d.get("index", 0)
                slot = tool_acc.setdefault(
                    idx, {"id": "", "type": "function", "function": {"name": "", "arguments": ""}}
                )
                if d.get("id"):
                    slot["id"] = d["id"]
                fn = d.get("function") or {}
                if fn.get("name"):
                    slot["function"]["name"] += fn["name"]
                if fn.get("arguments"):
                    slot["function"]["arguments"] += fn["arguments"]

    text = "".join(content)
    message: dict[str, Any] = {"role": "assistant", "content": text}
    if tool_acc:
        message["tool_calls"] = [tool_acc[i] for i in sorted(tool_acc)]
    yield "message", message
    if usage is None:
        usage = {
            "input_tokens": _estimate_tokens(json.dumps(messages)),
            "output_tokens": _estimate_tokens(text),
        }
    yield "usage", usage


async def _run_tool_with_keepalive(name: str, args: dict[str, Any]) -> AsyncIterator[tuple[str, Any]]:
    """Run one tool, yielding ("keepalive", None) every SSE_KEEPALIVE_SECONDS
    while it's still working, then ("result", result). An engine turn is the
    whole DAG, so this gap can be minutes long."""
    impl = TOOL_IMPLS.get(name)
    if impl is None:
        yield "result", {"error": f"unknown tool {name}"}
        return

    # A Task runs in its OWN copy of the context, so a ContextVar written
    # inside the tool would not be visible here -- which silently dropped
    # the live-session pointer the first time this was probed. Hand the
    # task an explicit Context we still hold a reference to, then copy the
    # pointer back out. (The blocking path awaits the tool inline and never
    # had this problem.)
    ctx = contextvars.copy_context()
    task = asyncio.get_running_loop().create_task(impl(args), context=ctx)
    while True:
        done, _ = await asyncio.wait({task}, timeout=SSE_KEEPALIVE_SECONDS)
        if done:
            break
        yield "keepalive", None

    pointer = ctx.get(demo_tools.DEMO_POINTER)
    if pointer is not None:
        demo_tools.DEMO_POINTER.set(pointer)
    try:
        yield "result", task.result()
    except Exception as err:
        logger.exception("tool %s failed", name)
        yield "result", {"error": f"tool {name} failed: {err}"}


async def stream_agent_turn(history: list[dict[str, str]]) -> AsyncIterator[dict[str, Any]]:
    """Same turn as run_agent_turn, emitted incrementally.

    Yields event dicts: {"kind": "text"|"reasoning", "text": str},
    {"kind": "keepalive"}, and exactly one terminal
    {"kind": "done", "reply": str, "input_tokens": int, "output_tokens": int}.
    The caller (the SSE route) is responsible for framing and for the
    live-session pointer; this generator only produces the turn.
    """
    messages: list[dict[str, Any]] = [{"role": "system", "content": SYSTEM_PROMPT}, *history]
    usage = {"input_tokens": 0, "output_tokens": 0}
    answer: list[str] = []

    def done(extra: str = "") -> dict[str, Any]:
        if extra:
            answer.append(extra)
        return {"kind": "done", "reply": "".join(answer), **usage}

    targets, fatal = _stream_targets()
    if fatal:
        yield {"kind": "text", "text": fatal}
        yield done(fatal)
        return

    async with httpx.AsyncClient() as client:
        for _ in range(4):  # cap tool-call round trips, same as run_agent_turn
            assistant: dict[str, Any] | None = None
            for attempt, (base_url, model, api_key, opts) in enumerate(targets):
                emitted = False
                try:
                    async for kind, value in _chat_stream(
                        client, base_url, model, api_key, messages, opts
                    ):
                        if kind == "message":
                            assistant = value
                        elif kind == "usage":
                            usage["input_tokens"] += value["input_tokens"]
                            usage["output_tokens"] += value["output_tokens"]
                        else:
                            emitted = True
                            if kind == "text":
                                answer.append(value)
                            yield {"kind": kind, "text": value}
                    break
                except Exception as err:
                    # Falling back after deltas are already on the wire would
                    # splice two different models' prose together, so only
                    # degrade while nothing has been emitted for this round.
                    last = attempt == len(targets) - 1
                    if last or emitted or not _is_infra_error(err):
                        logger.warning("stream: %s failed (%s), no usable fallback", model, err)
                        msg = f"\n\n[the model stream failed: {err}]" if emitted else (
                            "The primary model is unreachable and no fallback is available."
                        )
                        yield {"kind": "text", "text": msg}
                        yield done(msg)
                        return
                    logger.warning(
                        "stream: %s unreachable (%s), degrading to next target", model, err
                    )

            if assistant is None:
                yield done()
                return

            tool_calls = assistant.get("tool_calls")
            if not tool_calls:
                yield done()
                return

            # Same history-hygiene rule as run_agent_turn: keep only the
            # standard OpenAI chat fields, never a provider's extra
            # reasoning field, or the other provider 400s on fallback.
            messages.append(
                {
                    "role": assistant.get("role", "assistant"),
                    "content": assistant.get("content") or "",
                    "tool_calls": tool_calls,
                }
            )
            for tc in tool_calls:
                name = tc["function"]["name"]
                try:
                    args = json.loads(tc["function"].get("arguments") or "{}")
                except Exception:
                    args = {}
                result: Any = {"error": f"unknown tool {name}"}
                async for kind, value in _run_tool_with_keepalive(name, args):
                    if kind == "keepalive":
                        yield {"kind": "keepalive"}
                    else:
                        result = value
                messages.append(
                    {"role": "tool", "tool_call_id": tc["id"], "content": json.dumps(result)}
                )
        yield done("Reached the tool-call round limit without a final answer.")


# ---------------------------------------------------------------------------
# Per-context conversation history (in-memory).
# ---------------------------------------------------------------------------

CONTEXT_HISTORY: dict[str, list[dict[str, str]]] = {}

router = APIRouter()


@router.get("/.well-known/agent-card.json")
async def agent_card():
    return JSONResponse(CARD)


@router.get("/agent")
async def agent_chat_page():
    """Self-contained static chat UI: fetches the card client-side, talks
    to /a2a directly. No templating, no build step (src/static/agent.html)."""
    return FileResponse(STATIC_DIR / "agent.html")


@router.get("/")
async def root_redirect():
    # The engine doesn't otherwise use "/" (see src/main.py) — send visitors
    # straight to the human-facing chat interface.
    return RedirectResponse(url="/agent")


def _rpc_error(rpc_id: Any, code: int, message: str, status: int = 200) -> JSONResponse:
    return JSONResponse(
        {"jsonrpc": "2.0", "id": rpc_id, "error": {"code": code, "message": message}}, status_code=status
    )


class _Prepared(NamedTuple):
    """Everything both methods need after validation + the spend guard."""

    rpc_id: Any
    context_id: str
    history: list[dict[str, str]]
    text: str


async def _prepare_turn(request: Request, rpc: dict[str, Any]) -> _Prepared | JSONResponse:
    """Shared preamble for SendMessage and SendStreamingMessage: params
    validation, the spend guard, context history, and the per-request
    ContextVars the tool layer reads. Returns a JSONResponse on rejection."""
    rpc_id = rpc.get("id")
    params = rpc.get("params") or {}
    message = params.get("message") or {}
    parts = message.get("parts") or []
    text = "\n".join(p.get("text", "") for p in parts if p.get("text")).strip()
    if not text:
        return _rpc_error(rpc_id, -32602, "Invalid params: no text parts in message")

    # Spend guard (ported from the portfolio's agent/lib/spend-guard.ts, same
    # Neon ledger as the portfolio and rac origins): a fresh contextId means
    # a new session, same caveat as rac's port -- a hostile caller can dodge
    # the per-IP session cap by minting a new contextId every request, but
    # the token ceilings still bound total spend regardless.
    new_session = not message.get("contextId")
    try:
        verdict = await check_spend(client_ip(request.headers), new_session)
        if not verdict.allowed:
            return _rpc_error(
                rpc_id, -32000, f"Over today's budget ({verdict.reason}). Come back tomorrow.", status=403
            )
    except Exception as err:
        # Ledger unreachable != policy violation: fail OPEN on infra errors.
        logger.warning("spend-guard: ledger unavailable, letting request pass: %s", err)

    context_id = message.get("contextId") or str(uuid.uuid4())
    history = CONTEXT_HISTORY.setdefault(context_id, [])
    history.append({"role": "user", "content": text})

    # Demo write-tools (src/demo_tools.py) read the contextId via this
    # ContextVar rather than threading it through every TOOL_IMPLS
    # signature; reset the pointer so a stale one from an earlier request
    # on this same asyncio task/instance can never leak into this reply.
    demo_tools.A2A_CONTEXT_ID.set(context_id)
    demo_tools.DEMO_POINTER.set(None)

    # Loop safety for the handback tool: an inbound request that already
    # carries our hop marker came from the portfolio (or a longer chain),
    # and handing back would cycle. See src/handback.py.
    handback.CONTEXT_ID.set(context_id)
    handback.INBOUND_HOP_DEPTH.set(handback.inbound_hop_depth(request.headers, params, message))

    return _Prepared(rpc_id, context_id, history, text)


def _live_session_part() -> dict[str, Any] | None:
    """The demo tools' session pointer, if one ran this turn.

    Contract (pinned): mediaType application/x-portfolio-live-session+json,
    text is the JSON string, not embedded as a nested object -- matches how
    the existing text parts carry a plain string.
    """
    pointer = demo_tools.DEMO_POINTER.get()
    if pointer is None:
        return None
    return {"mediaType": LIVE_SESSION_MEDIA_TYPE, "text": json.dumps(pointer)}


@router.post("/a2a")
async def a2a_rpc(request: Request):
    try:
        rpc = await request.json()
    except Exception:
        return _rpc_error(None, -32700, "Parse error")

    rpc_id = rpc.get("id")
    if rpc.get("jsonrpc") != "2.0":
        return _rpc_error(rpc_id, -32600, "Invalid Request: jsonrpc must be '2.0'")
    method = rpc.get("method")
    if method == "SendMessage":
        return await _send_message(request, rpc)
    if method == "SendStreamingMessage" and STREAMING_ENABLED:
        return await _send_streaming_message(request, rpc)
    return _rpc_error(rpc_id, -32601, f"Method not found: {method}")


async def _send_message(request: Request, rpc: dict[str, Any]):
    prepared = await _prepare_turn(request, rpc)
    if isinstance(prepared, JSONResponse):
        return prepared
    rpc_id, context_id, history, _ = prepared

    try:
        turn = await run_agent_turn(history)
    except Exception as e:
        logger.exception("agent turn failed")
        return _rpc_error(rpc_id, -32603, f"agent turn failed: {e}")

    reply_text = turn.reply
    try:
        await record_usage(turn.input_tokens, turn.output_tokens)
    except Exception as err:
        logger.warning("spend-guard: usage recording failed: %s", err)

    history.append({"role": "assistant", "content": reply_text})

    reply_parts: list[dict[str, Any]] = [{"text": reply_text}]
    pointer_part = _live_session_part()
    if pointer_part is not None:
        reply_parts.append(pointer_part)

    reply = {
        "messageId": str(uuid.uuid4()),
        "contextId": context_id,
        "taskId": "",
        "role": "ROLE_AGENT",
        "parts": reply_parts,
    }
    return JSONResponse({"jsonrpc": "2.0", "id": rpc_id, "result": {"message": reply}})


async def _send_streaming_message(request: Request, rpc: dict[str, Any]):
    prepared = await _prepare_turn(request, rpc)
    if isinstance(prepared, JSONResponse):
        return prepared
    rpc_id, context_id, history, _ = prepared
    message_id = str(uuid.uuid4())

    def frame(parts: list[dict[str, Any]] | None, final: bool) -> str:
        envelope = {
            "jsonrpc": "2.0",
            "id": rpc_id,
            "result": {
                "message": {
                    "messageId": message_id,
                    "contextId": context_id,
                    "taskId": "",
                    "role": "ROLE_AGENT",
                    "parts": parts or [],
                },
                "final": final,
            },
        }
        return f"data: {json.dumps(envelope)}\n\n"

    def error_frame(message: str) -> str:
        # Once a 200 + SSE headers are on the wire there is no HTTP-level
        # error left to return, and a client that never sees a terminator
        # hangs. An error frame IS the terminator.
        envelope = {
            "jsonrpc": "2.0",
            "id": rpc_id,
            "error": {"code": -32603, "message": message},
        }
        return f"data: {json.dumps(envelope)}\n\n"

    async def body() -> AsyncIterator[str]:
        reply_text = ""
        input_tokens = output_tokens = 0
        failed: str | None = None
        try:
            async for event in stream_agent_turn(history):
                kind = event["kind"]
                if kind == "keepalive":
                    yield ": keep-alive\n\n"
                elif kind == "text":
                    yield frame([{"text": event["text"]}], False)
                elif kind == "reasoning":
                    yield frame(
                        [{"mediaType": REASONING_MEDIA_TYPE, "text": event["text"]}], False
                    )
                elif kind == "done":
                    reply_text = event["reply"]
                    input_tokens = event["input_tokens"]
                    output_tokens = event["output_tokens"]
        except Exception as e:
            logger.exception("streaming agent turn failed")
            failed = f"agent turn failed: {e}"
        finally:
            # A browser closing the stream mid-flight must not lose spend
            # accounting, nor leave a user message in CONTEXT_HISTORY with
            # no assistant reply after it.
            history.append({"role": "assistant", "content": reply_text})
            try:
                await record_usage(input_tokens, output_tokens)
            except Exception as err:
                logger.warning("spend-guard: usage recording failed: %s", err)

        if failed:
            yield error_frame(failed)
            return
        # Terminal frame carries the live-session pointer when a demo tool
        # ran this turn -- the leaf's "last one wins" pointer handling is
        # unchanged, it just arrives at the end of the stream instead of
        # alongside the answer.
        pointer_part = _live_session_part()
        yield frame([pointer_part] if pointer_part else [], True)

    return StreamingResponse(
        body(),
        media_type="text/event-stream",
        headers={
            "cache-control": "no-cache",
            "connection": "keep-alive",
            # Defeat proxy-level response buffering (nginx and friends);
            # without it the whole stream can arrive as one flush.
            "x-accel-buffering": "no",
        },
    )
