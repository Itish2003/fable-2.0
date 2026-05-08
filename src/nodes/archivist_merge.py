"""Archivist merge node.

Applies the ArchivistDelta produced by the archivist LlmAgent to canonical
state fields. Replaces the imperative 13-tool loop the archivist used to
run (deleted with src/tools/archivist_tools.py).

Every state mutation that lived in those tools lives here. Same
behaviour, no LLM-driven loop, no exit conditions, no per-tool budgets.
"""

from __future__ import annotations

import json
import logging
from typing import Any, AsyncGenerator

from sqlalchemy import select

from google.adk.agents.context import Context
from google.adk.events import Event
from google.adk.workflow import node

from src.database import AsyncSessionLocal
from src.services.embedding_service import get_embedding
from src.state.lore_models import LoreEdge, LoreEmbedding, LoreNode
from src.utils.sanitizer import sanitize_context

logger = logging.getLogger("fable.archivist_merge")

# Trust shifts smaller than this aren't persisted as graph edges -- they're
# already tracked at fine resolution in state.active_characters[*].trust_level.
_LORE_EDGE_TRUST_THRESHOLD = 20

_PROTAGONIST_STATE_KEY = "protagonist_node_name"
_PROTAGONIST_PREFIX = "PROTAGONIST::"


def _protagonist_name(state) -> str:
    """Per-session protagonist sentinel. Mirrors archivist_tools._protagonist_name.
    Falls back to legacy global "PROTAGONIST" if state hasn't been initialised."""
    name = state.get(_PROTAGONIST_STATE_KEY) if hasattr(state, "get") else None
    if name and isinstance(name, str) and name.startswith(_PROTAGONIST_PREFIX):
        return name
    return "PROTAGONIST"


async def _upsert_lore_node(db, name: str, node_type: str = "character") -> LoreNode:
    stmt = select(LoreNode).where(LoreNode.name == name)
    n = (await db.execute(stmt)).scalar_one_or_none()
    if n is None:
        n = LoreNode(name=name, node_type=node_type, attributes={})
        db.add(n)
        await db.flush()
    return n


async def _persist_relationship_edges(
    state, edge_writes: list[tuple[str, int, str]]
) -> None:
    """For each (target_name, trust_delta, disposition) where |delta| >= threshold,
    upsert a LoreEdge from PROTAGONIST::<session> to target. Best-effort;
    edge persistence failures don't block state writes."""
    if not edge_writes:
        return
    try:
        protagonist_name = _protagonist_name(state)
        async with AsyncSessionLocal() as db:
            proto = await _upsert_lore_node(db, protagonist_name)
            for target_name, trust_delta, disposition in edge_writes:
                if abs(int(trust_delta)) < _LORE_EDGE_TRUST_THRESHOLD:
                    continue
                target = await _upsert_lore_node(db, target_name)
                stmt = select(LoreEdge).where(
                    LoreEdge.source_id == proto.id,
                    LoreEdge.target_id == target.id,
                )
                edge = (await db.execute(stmt)).scalar_one_or_none()
                if edge is None:
                    db.add(
                        LoreEdge(
                            source_id=proto.id,
                            target_id=target.id,
                            relationship_type=disposition or "neutral",
                            visibility_whitelist=[protagonist_name, target_name],
                        )
                    )
                else:
                    edge.relationship_type = disposition or edge.relationship_type
                    edge.visibility_whitelist = [protagonist_name, target_name]
            await db.commit()
    except Exception as e:
        logger.warning("archivist_merge: LoreEdge persist failed: %s", e)


async def _persist_lore_commits(state, lore_commits: list[dict]) -> None:
    """Mirrors commit_lore tool. Upserts a LoreNode + LoreEmbedding row for
    each entry so later chapters can find it via lore_lookup."""
    if not lore_commits:
        return
    universes = state.get("universes") or []
    fallback_universe = universes[0] if universes else "unknown"
    for entry in lore_commits:
        try:
            entity_name = sanitize_context(entry.get("entity_name") or "")
            if not entity_name:
                continue
            node_type = entry.get("node_type") or "character"
            universe = entry.get("universe") or fallback_universe
            attributes = entry.get("attributes") or {}
            chunk_payload = (
                f"{entity_name}\n{json.dumps(attributes, sort_keys=True, default=str)}"
            )
            vector = await get_embedding(chunk_payload)
            async with AsyncSessionLocal() as db:
                stmt = select(LoreNode).where(LoreNode.name == entity_name)
                n = (await db.execute(stmt)).scalar_one_or_none()
                if n is None:
                    n = LoreNode(
                        name=entity_name,
                        node_type=node_type,
                        attributes=dict(attributes),
                    )
                    db.add(n)
                    await db.flush()
                else:
                    merged = dict(n.attributes or {})
                    merged.update(attributes)
                    n.attributes = merged
                db.add(
                    LoreEmbedding(
                        node_id=n.id,
                        universe=universe,
                        volume="archivist_runtime",
                        chunk_text=chunk_payload,
                        embedding=vector,
                    )
                )
                await db.commit()
        except Exception as e:
            logger.warning("archivist_merge: lore_commit failed for %r: %s", entry, e)


@node(name="archivist_merge")
async def archivist_merge(
    ctx: Context, node_input: Any
) -> AsyncGenerator[Event, None]:
    delta = ctx.state.get("archivist_delta") or {}
    if not delta:
        logger.info("archivist_merge: empty delta, no state changes")
        if False:
            yield
        return

    # ─── 1. character_updates ─────────────────────────────────────────────
    actives = dict(ctx.state.get("active_characters") or {})
    edge_writes: list[tuple[str, int, str]] = []
    for raw_name, raw_upd in (delta.get("character_updates") or {}).items():
        name = sanitize_context(raw_name)
        upd = dict(raw_upd or {})
        cur = dict(actives.get(name) or {})
        # Initialize defaults on first sighting (mirrors update_relationship)
        cur.setdefault("trust_level", 0)
        cur.setdefault("disposition", "neutral")
        cur.setdefault("is_present", True)
        cur.setdefault("dynamic_tags", [])

        trust_delta = int(upd.get("trust_delta") or 0)
        if trust_delta:
            cur["trust_level"] = max(-100, min(100, int(cur["trust_level"]) + trust_delta))
        disposition = sanitize_context(upd.get("disposition") or "")
        if disposition:
            cur["disposition"] = disposition
        tags = [sanitize_context(t) for t in (upd.get("dynamic_tags") or [])]
        if tags:
            cur["dynamic_tags"] = list({*cur.get("dynamic_tags", []), *tags})
        if upd.get("is_present") is not None:
            cur["is_present"] = bool(upd["is_present"])
        actives[name] = cur

        if abs(trust_delta) >= _LORE_EDGE_TRUST_THRESHOLD:
            edge_writes.append((name, trust_delta, cur["disposition"]))
    ctx.state["active_characters"] = actives

    # ─── 2. voice_updates ────────────────────────────────────────────────
    voices = dict(ctx.state.get("character_voices") or {})
    for raw_name, raw_vu in (delta.get("voice_updates") or {}).items():
        name = sanitize_context(raw_name)
        vu = dict(raw_vu or {})
        cur = dict(voices.get(name) or {})
        if vu.get("speech_patterns"):
            cur["speech_patterns"] = sanitize_context(vu["speech_patterns"])
        if vu.get("vocabulary_level"):
            cur["vocabulary_level"] = sanitize_context(vu["vocabulary_level"])
        if vu.get("verbal_tics"):
            cur["verbal_tics"] = list(
                {*cur.get("verbal_tics", []), *(sanitize_context(t) for t in vu["verbal_tics"])}
            )
        if vu.get("topics_to_avoid"):
            cur["topics_to_avoid"] = list(
                {*cur.get("topics_to_avoid", []), *(sanitize_context(t) for t in vu["topics_to_avoid"])}
            )
        if vu.get("example_dialogue"):
            cur["example_dialogue"] = sanitize_context(vu["example_dialogue"])
        voices[name] = cur
    ctx.state["character_voices"] = voices

    # ─── 3. new_divergences ──────────────────────────────────────────────
    divs = list(ctx.state.get("active_divergences") or [])
    for d in (delta.get("new_divergences") or []):
        divs.append(
            {
                "event_id": sanitize_context(d.get("canon_event_id") or ""),
                "description": sanitize_context(d.get("description") or ""),
                "ripple_effects": [
                    sanitize_context(r) for r in (d.get("ripple_effects") or [])
                ],
            }
        )

    # ─── 4. materialized_ripples ────────────────────────────────────────
    for mr in (delta.get("materialized_ripples") or []):
        target_id = sanitize_context(mr.get("divergence_event_id") or "")
        desc = sanitize_context(mr.get("materialization") or "")
        if not target_id:
            continue
        matched = False
        for d in divs:
            if isinstance(d, dict) and d.get("event_id") == target_id:
                materialized = list(d.get("materialized_ripples") or [])
                materialized.append(desc)
                d["materialized_ripples"] = materialized
                matched = True
                break
        if not matched:
            divs.append(
                {
                    "event_id": target_id,
                    "description": "(referenced by materialized_ripples)",
                    "ripple_effects": [],
                    "materialized_ripples": [desc],
                }
            )
    ctx.state["active_divergences"] = divs

    # ─── 5. canon_event_status_updates ───────────────────────────────────
    canon = dict(ctx.state.get("canon_timeline") or {})
    events = list(canon.get("events") or [])
    valid_statuses = {"upcoming", "occurred", "modified", "prevented"}
    for upd in (delta.get("canon_event_status_updates") or []):
        target = sanitize_context(upd.get("event_name") or "")
        new_status = (upd.get("new_status") or "occurred").strip().lower()
        if new_status not in valid_statuses:
            new_status = "occurred"
        notes = sanitize_context(upd.get("notes") or "")
        for ev in events:
            if isinstance(ev, dict) and (
                ev.get("name") == target or ev.get("event_id") == target
            ):
                ev["status"] = new_status
                if notes:
                    ev["notes"] = notes
                break
    canon["events"] = events
    ctx.state["canon_timeline"] = canon

    # ─── 6. timeline date / note ────────────────────────────────────────
    if delta.get("new_timeline_date"):
        ctx.state["current_timeline_date"] = sanitize_context(delta["new_timeline_date"])

    # ─── 7. power_strain ────────────────────────────────────────────────
    pd = dict(ctx.state.get("power_debt") or {})
    pd.setdefault("strain_level", 0)
    pd.setdefault("recent_feats", [])
    feats = list(pd["recent_feats"])
    for entry in (delta.get("power_strain") or []):
        increase = int(entry.get("strain_increase") or 0)
        if increase <= 0:
            continue
        pd["strain_level"] = int(pd["strain_level"]) + increase
        power_used = sanitize_context(entry.get("power_used") or "")
        if power_used and power_used not in feats:
            feats.append(power_used)
    pd["recent_feats"] = feats
    ctx.state["power_debt"] = pd

    # ─── 8. pending_consequences ────────────────────────────────────────
    if delta.get("pending_consequences"):
        stakes = dict(ctx.state.get("stakes_and_consequences") or {})
        pending = list(stakes.get("pending_consequences") or [])
        for pc in delta["pending_consequences"]:
            pending.append(
                {
                    "action": sanitize_context(pc.get("action") or ""),
                    "predicted_consequence": sanitize_context(
                        pc.get("predicted_consequence") or ""
                    ),
                    "due_by_chapter": int(pc.get("due_by_chapter") or 0),
                    "overdue": False,
                }
            )
        stakes["pending_consequences"] = pending
        ctx.state["stakes_and_consequences"] = stakes

    # ─── 9. violations ──────────────────────────────────────────────────
    if delta.get("violations"):
        log = list(ctx.state.get("violation_log") or [])
        for v in delta["violations"]:
            log.append(
                {
                    "type": sanitize_context(v.get("violation_type") or ""),
                    "character": sanitize_context(v.get("character") or ""),
                    "concept": sanitize_context(v.get("concept") or ""),
                    "quote": sanitize_context(v.get("quote") or ""),
                    "severity": sanitize_context(v.get("severity") or ""),
                }
            )
        ctx.state["violation_log"] = log

    # ─── 10. side-effect persistence (LoreEdges + LoreCommits) ─────────
    # Best-effort, fire-and-forget; failures don't block state writes.
    await _persist_relationship_edges(ctx.state, edge_writes)
    await _persist_lore_commits(ctx.state, list(delta.get("lore_commits") or []))

    logger.info(
        "archivist_merge: applied delta (chars=%d voices=%d divs=%d strain=%d violations=%d)",
        len(delta.get("character_updates") or {}),
        len(delta.get("voice_updates") or {}),
        len(delta.get("new_divergences") or []),
        len(delta.get("power_strain") or []),
        len(delta.get("violations") or []),
    )
    if False:
        yield  # pragma: no cover  -- async-generator shape
