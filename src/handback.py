"""Hand a visitor's off-topic question back up to the portfolio root agent.

This agent owns exactly one project. When a visitor asks about a DIFFERENT
project, asks what else Itish has built, or wants a comparison this agent
cannot ground in its own repo, the honest move is to ask the root agent
that knows the whole portfolio -- not to answer from general knowledge
about a repo we do not own. `ask_portfolio` is that one tool.

Target discovery (no hardcoded host)
------------------------------------
The portfolio's JSON-RPC URL is read from its own agent card at runtime
(`supportedInterfaces` -> the JSONRPC binding), exactly the way the
portfolio discovers project agents from live cards. The only configured
value is where that card lives:

    PORTFOLIO_AGENT_CARD_URL=https://<portfolio-host>/.well-known/agent-card.json

Unset -> the tool degrades to "not configured" and tells the visitor to
ask the root agent above. It never falls back to a baked-in host: the
portfolio's Vercel hostname is generated and has changed before, which is
the whole reason this is discovery + config rather than a constant.

Loop safety
-----------
portfolio -> fable -> portfolio -> fable is a cycle, and every hop is a
full model turn. Four independent layers, cheapest first:

1. HOP MARKER (`message.metadata["x-portfolio-hop"]` + the
   `x-portfolio-hop-depth` header, both set on the way out and read on
   the way in). Depth >= MAX_HOP_DEPTH inbound -> refuse. Honest caveat:
   this layer is INERT TODAY. The portfolio's `delegate` sends plain text
   and does not propagate the marker, so a portfolio-originated request
   arrives unmarked. It starts working the moment the portfolio (or any
   relay) forwards it, and it is the only layer that is correct rather
   than merely bounding.
2. IN-FLIGHT RE-ENTRANCY FLAG (module-level). While an outbound handback
   from this instance is still awaiting, any further handback is refused.
   This is what actually breaks the tight cycle today: a re-entrant
   fable request caused by our own outbound call arrives while that call
   is still in flight. Instance-local -- a re-entry landing on a
   different serverless instance dodges it, hence layer 3.
3. WINDOWED CAP (HANDBACK_MAX_PER_MINUTE, default 3, module-level). Each
   hop mints a fresh contextId, so a per-context cap alone cannot bound a
   cycle; a per-minute ceiling can. This is the runaway-cost stop.
4. PER-CONTEXT CAP (HANDBACK_MAX_PER_CONTEXT, default 1). Not a cycle
   guard -- it stops one chatty conversation from paying for nested model
   turns over and over.

Plus a hard timeout: a handback is at least two nested model turns, but
vercel.json caps this whole function at maxDuration 300s and the model
still needs a wrapping turn after the tool returns. So the outbound read
budget is HANDBACK_TIMEOUT_SECONDS (default 170), NOT the 540s the
portfolio's own bridge allows -- fable does not have 540s to give. On
timeout the tool degrades to "ask the root agent above" rather than
hanging the visitor's request until the platform kills it.
"""

import logging
import os
import time
from collections import deque
from contextvars import ContextVar
from typing import Any

import httpx

logger = logging.getLogger("fable.handback")

PORTFOLIO_CARD_URL = os.getenv("PORTFOLIO_AGENT_CARD_URL")
HANDBACK_TIMEOUT_SECONDS = float(os.getenv("HANDBACK_TIMEOUT_SECONDS", "170"))
HANDBACK_MAX_PER_CONTEXT = int(os.getenv("HANDBACK_MAX_PER_CONTEXT", "1"))
HANDBACK_MAX_PER_MINUTE = int(os.getenv("HANDBACK_MAX_PER_MINUTE", "3"))
MAX_HOP_DEPTH = 1

THIS_PROJECT = "fable-2.0"
USER_AGENT = "fable-2.0-a2a-handback/1"

DEGRADE_NOTE = (
    "Could not reach the portfolio root agent. Tell the visitor to ask the "
    "root agent in the chat above -- do not answer about another project "
    "from general knowledge."
)

# Set by src/a2a_agent.py at the top of every request, same pattern as
# demo_tools.A2A_CONTEXT_ID (avoids threading them through TOOL_IMPLS).
CONTEXT_ID: ContextVar[str | None] = ContextVar("HANDBACK_CONTEXT_ID", default=None)
INBOUND_HOP_DEPTH: ContextVar[int] = ContextVar("HANDBACK_INBOUND_HOP_DEPTH", default=0)

_in_flight = 0
_recent_calls: deque[float] = deque()
_per_context_counts: dict[str, int] = {}

# Cached discovery result: the portfolio's card rarely moves within an
# instance's lifetime, and a cold start re-discovers.
_cached_rpc_url: str | None = None


def inbound_hop_depth(headers: Any, params: dict[str, Any], message: dict[str, Any]) -> int:
    """Read our hop marker off an inbound request. 0 when absent (unmarked)."""
    for container in (message.get("metadata"), params.get("metadata")):
        if isinstance(container, dict):
            hop = container.get("x-portfolio-hop")
            if isinstance(hop, dict):
                try:
                    return int(hop.get("depth") or 0)
                except (TypeError, ValueError):
                    return 0
    raw = None
    try:
        raw = headers.get("x-portfolio-hop-depth")
    except Exception:
        raw = None
    if raw:
        try:
            return int(raw)
        except ValueError:
            return 0
    return 0


def _windowed_allow() -> bool:
    now = time.monotonic()
    while _recent_calls and now - _recent_calls[0] > 60.0:
        _recent_calls.popleft()
    return len(_recent_calls) < HANDBACK_MAX_PER_MINUTE


async def _discover_rpc_url() -> str | None:
    global _cached_rpc_url
    if _cached_rpc_url:
        return _cached_rpc_url
    if not PORTFOLIO_CARD_URL:
        return None
    async with httpx.AsyncClient(timeout=10.0) as client:
        res = await client.get(PORTFOLIO_CARD_URL, headers={"user-agent": USER_AGENT})
    res.raise_for_status()
    card = res.json()
    for iface in card.get("supportedInterfaces") or []:
        if (iface.get("protocolBinding") or "").upper() == "JSONRPC" and iface.get("url"):
            _cached_rpc_url = iface["url"]
            logger.info("handback: discovered portfolio JSONRPC url %s", _cached_rpc_url)
            return _cached_rpc_url
    return None


async def ask_portfolio(args: dict[str, Any]) -> dict[str, Any]:
    """Tool impl. Returns a dict the model reads; never raises."""
    global _in_flight

    question = (args.get("question") or "").strip()
    if not question:
        return {"handed_back": False, "note": "No question supplied."}

    if INBOUND_HOP_DEPTH.get() >= MAX_HOP_DEPTH:
        return {
            "handed_back": False,
            "note": (
                "This request already came from the portfolio root agent, so "
                "handing back would loop. Answer only about fable-2.0 and "
                "tell the visitor the root agent handles other projects."
            ),
        }
    if _in_flight > 0:
        return {"handed_back": False, "note": "A handback is already in flight. " + DEGRADE_NOTE}
    if not _windowed_allow():
        return {"handed_back": False, "note": "Handback rate limit reached. " + DEGRADE_NOTE}

    context_id = CONTEXT_ID.get() or "_no_context"
    if _per_context_counts.get(context_id, 0) >= HANDBACK_MAX_PER_CONTEXT:
        return {
            "handed_back": False,
            "note": (
                "Already handed back once in this conversation. Tell the "
                "visitor to continue in the root chat above for other projects."
            ),
        }

    try:
        rpc_url = await _discover_rpc_url()
    except Exception as err:
        logger.warning("handback: card discovery failed: %s", err)
        return {"handed_back": False, "note": DEGRADE_NOTE}
    if not rpc_url:
        return {
            "handed_back": False,
            "note": (
                "The portfolio root agent's address is not configured on this "
                "deployment (PORTFOLIO_AGENT_CARD_URL). " + DEGRADE_NOTE
            ),
        }

    hop_depth = INBOUND_HOP_DEPTH.get() + 1
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "SendMessage",
        "params": {
            "message": {
                "role": "ROLE_USER",
                "parts": [
                    {
                        "text": (
                            f"{question}\n\n"
                            f"(Asked by the {THIS_PROJECT} project agent, on behalf of a "
                            f"visitor who is currently in the {THIS_PROJECT} chat -- so do "
                            f"not route this back to {THIS_PROJECT}.)"
                        )
                    }
                ],
                "metadata": {"x-portfolio-hop": {"depth": hop_depth, "origin": THIS_PROJECT}},
            }
        },
    }
    headers = {
        "content-type": "application/json",
        "user-agent": USER_AGENT,
        "x-portfolio-hop-depth": str(hop_depth),
        "x-portfolio-hop-origin": THIS_PROJECT,
    }

    _in_flight += 1
    _recent_calls.append(time.monotonic())
    _per_context_counts[context_id] = _per_context_counts.get(context_id, 0) + 1
    try:
        async with httpx.AsyncClient(timeout=HANDBACK_TIMEOUT_SECONDS) as client:
            res = await client.post(rpc_url, json=payload, headers=headers)
        if res.status_code >= 400:
            logger.warning("handback: portfolio answered HTTP %s: %s", res.status_code, res.text[:500])
            return {"handed_back": False, "note": DEGRADE_NOTE}
        body = res.json()
    except httpx.TimeoutException:
        logger.warning("handback: portfolio timed out after %ss", HANDBACK_TIMEOUT_SECONDS)
        return {"handed_back": False, "note": "The root agent took too long. " + DEGRADE_NOTE}
    except Exception as err:
        logger.warning("handback: call failed: %s", err)
        return {"handed_back": False, "note": DEGRADE_NOTE}
    finally:
        _in_flight -= 1

    if body.get("error"):
        logger.warning("handback: portfolio returned JSON-RPC error %s", body["error"])
        return {"handed_back": False, "note": DEGRADE_NOTE}

    reply = ((body.get("result") or {}).get("message") or {})
    answer = "\n".join(
        p.get("text", "")
        for p in (reply.get("parts") or [])
        if p.get("text") and not p.get("mediaType")
    ).strip()
    if not answer:
        return {"handed_back": False, "note": DEGRADE_NOTE}

    return {
        "handed_back": True,
        "source": "itish-portfolio root agent",
        "answer": answer,
        "note": (
            "Relay this answer and credit the root agent for it. Do not add "
            "claims of your own about projects other than fable-2.0."
        ),
    }
