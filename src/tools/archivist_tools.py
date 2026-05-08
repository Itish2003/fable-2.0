import json
import logging

from src.state.models import FableAgentState, CharacterState, DivergenceRecord
from src.database import AsyncSessionLocal
from src.state.lore_models import LoreEmbedding, LoreEdge, LoreNode
from src.services.embedding_service import get_embedding
from src.utils.sanitizer import sanitize_context

from google.adk.tools.tool_context import ToolContext
from sqlalchemy import select

logger = logging.getLogger("fable.tools")

# Fable models a single-protagonist crossover narrative: every relationship
# edge in the GraphRAG store has the user's character on one side. We use a
# canonical sentinel name so edges remain stable across sessions even though
# the protagonist's display name lives in the free-form story_premise.
PROTAGONIST_NODE_NAME = "PROTAGONIST"

# Trust shifts smaller than this aren't persisted as graph edges — they're
# already tracked at fine resolution in state.active_characters[*].trust_level.
LORE_EDGE_TRUST_THRESHOLD = 20


async def _upsert_lore_node(db, name: str, node_type: str = "character") -> LoreNode:
    """Find a LoreNode by name or create one. Returns a session-bound row
    with `id` populated (uses flush to assign the PK before commit)."""
    stmt = select(LoreNode).where(LoreNode.name == name)
    result = await db.execute(stmt)
    node = result.scalar_one_or_none()
    if node is None:
        node = LoreNode(name=name, node_type=node_type, attributes={})
        db.add(node)
        await db.flush()
    return node


async def update_relationship(
    target_name: str,
    trust_delta: int,
    disposition: str,
    dynamic_tags: list[str],
    tool_context: ToolContext,
) -> str:
    """
    Updates the trust level, disposition, and status tags for a specific character in the current scene.

    Args:
        target_name: The exact name of the character.
        trust_delta: The change in trust (-100 to 100). Positive builds trust, negative damages it.
        disposition: A short tag describing their current mood/attitude (e.g., 'angry', 'intrigued').
        dynamic_tags: A list of current status effects (e.g., 'wounded', 'suspicious', 'exhausted').
    """
    state = FableAgentState(**tool_context.state.to_dict())

    # Sanitize inputs
    target_name = sanitize_context(target_name)
    disposition = sanitize_context(disposition)
    dynamic_tags = [sanitize_context(tag) for tag in dynamic_tags]

    if target_name not in state.active_characters:
        # If they aren't in the active state yet, initialize them
        state.active_characters[target_name] = CharacterState(
            trust_level=0, disposition="neutral", is_present=True
        )

    char_state = state.active_characters[target_name]

    # Apply delta and clamp between -100 and 100
    new_trust = char_state.trust_level + trust_delta
    char_state.trust_level = max(-100, min(100, new_trust))

    char_state.disposition = disposition
    char_state.dynamic_tags = dynamic_tags

    # Persist the mutation back to ctx.state so ADK records the state_delta
    tool_context.state["active_characters"] = {
        k: v.model_dump() for k, v in state.active_characters.items()
    }

    # Persist significant relationship shifts as a LoreEdge so future graph
    # retrieval can reason about who-knows-whom. Edge source is the canonical
    # PROTAGONIST sentinel (Fable is single-protagonist by design). The
    # visibility_whitelist gates the Plan's epistemic boundary -- only the
    # two endpoints can traverse this edge during search.
    if abs(trust_delta) >= LORE_EDGE_TRUST_THRESHOLD:
        try:
            async with AsyncSessionLocal() as db:
                proto = await _upsert_lore_node(db, PROTAGONIST_NODE_NAME)
                target = await _upsert_lore_node(db, target_name)

                stmt = select(LoreEdge).where(
                    LoreEdge.source_id == proto.id,
                    LoreEdge.target_id == target.id,
                )
                result = await db.execute(stmt)
                edge = result.scalar_one_or_none()

                if edge is None:
                    db.add(LoreEdge(
                        source_id=proto.id,
                        target_id=target.id,
                        relationship_type=disposition,
                        visibility_whitelist=[PROTAGONIST_NODE_NAME, target_name],
                    ))
                else:
                    edge.relationship_type = disposition
                    edge.visibility_whitelist = [PROTAGONIST_NODE_NAME, target_name]

                await db.commit()
        except Exception as e:
            # Edge persistence is best-effort; state mutation already succeeded.
            logger.warning(
                "update_relationship: LoreEdge persist failed for %s: %s",
                target_name,
                e,
            )

    return f"Successfully updated relationship for {target_name}. New trust level: {char_state.trust_level}."


async def record_divergence(
    canon_event_id: str,
    description: str,
    ripple_effects: list[str],
    tool_context: ToolContext,
) -> str:
    """
    Logs a Butterfly Effect. Call this whenever the protagonist's actions cause a deviation
    from the established canon timeline.

    Args:
        canon_event_id: A brief identifier for the original canon event that was altered.
        description: A clear explanation of what changed in this timeline.
        ripple_effects: A list of anticipated future consequences caused by this change.
    """
    state = FableAgentState(**tool_context.state.to_dict())

    # Sanitize inputs
    canon_event_id = sanitize_context(canon_event_id)
    description = sanitize_context(description)
    ripple_effects = [sanitize_context(effect) for effect in ripple_effects]

    new_divergence = DivergenceRecord(
        event_id=canon_event_id,
        description=description,
        ripple_effects=ripple_effects
    )
    state.active_divergences.append(new_divergence)
    tool_context.state["active_divergences"] = [d.model_dump() for d in state.active_divergences]
    return f"Divergence recorded: {canon_event_id}. The timeline has been altered."


async def track_power_strain(
    power_used: str,
    strain_increase: int,
    tool_context: ToolContext,
) -> str:
    """
    Updates the protagonist's power debt. Call this when the protagonist uses a significant or costly ability.

    Args:
        power_used: The name of the power or technique used.
        strain_increase: The amount of strain added (1-100). Heavy magic should cost more.
    """
    state = FableAgentState(**tool_context.state.to_dict())

    power_used = sanitize_context(power_used)

    if strain_increase <= 0:
        return "No significant strain detected."

    state.power_debt.strain_level += strain_increase
    if power_used not in state.power_debt.recent_feats:
        state.power_debt.recent_feats.append(power_used)

    tool_context.state["power_debt"] = state.power_debt.model_dump()

    warning = ""
    if state.power_debt.strain_level > 80:
        warning = " WARNING: Strain level critical (>80). Exhaustion penalties imminent."

    return f"Power strain increased by {strain_increase}. Current debt: {state.power_debt.strain_level}.{warning}"


async def advance_timeline(
    new_date: str,
    event_description: str,
    tool_context: ToolContext,
) -> str:
    """
    Advances the world clock. Call this to explicitly jump forward in time.

    Args:
        new_date: The new in-world date/time (e.g., '2095-04-06 Morning').
        event_description: A brief summary of what happened during the time skip.
    """
    new_date = sanitize_context(new_date)
    event_description = sanitize_context(event_description)

    tool_context.state["current_timeline_date"] = new_date
    return f"Timeline advanced to {new_date}."


async def commit_lore(
    entity_name: str,
    metadata: dict,
    tool_context: ToolContext,
) -> dict:
    """
    Finalizes a background research pass into the GraphRAG store.

    Upserts a ``LoreNode`` for ``entity_name`` (default node_type='character'
    if not provided in metadata) and writes a ``LoreEmbedding`` row carrying
    the entity name + serialized metadata as the chunk text. Mirrors the
    ingestion pattern in ``src/nodes/lore_ingestion.py``.

    Args:
        entity_name: The canonical name of the entity (character, location, faction, event).
        metadata: Free-form attributes. Optional keys: ``node_type``,
            ``universe``, ``volume``. All other keys are persisted onto
            ``LoreNode.attributes``.
    """
    entity_name = sanitize_context(entity_name)
    metadata = metadata or {}

    node_type = metadata.get("node_type", "character")
    universe = metadata.get("universe", tool_context.state.get("universe", "unknown"))
    volume = metadata.get("volume", "archivist_runtime")

    # Build the chunk_text payload: entity_name + metadata so the embedding
    # captures both the identity and the new facts.
    chunk_payload = f"{entity_name}\n{json.dumps(metadata, sort_keys=True, default=str)}"

    try:
        vector = await get_embedding(chunk_payload)
    except Exception as e:
        logger.error(f"commit_lore: embedding failed for {entity_name}: {e}")
        return {"committed": False, "entity_name": entity_name, "error": str(e)}

    try:
        async with AsyncSessionLocal() as db:
            # Upsert the LoreNode
            stmt = select(LoreNode).where(LoreNode.name == entity_name)
            result = await db.execute(stmt)
            node = result.scalar_one_or_none()

            if node is None:
                node = LoreNode(
                    name=entity_name,
                    node_type=node_type,
                    attributes={k: v for k, v in metadata.items() if k not in ("node_type", "universe", "volume")},
                )
                db.add(node)
                await db.flush()  # populate node.id
            else:
                # Merge new attributes onto the existing node
                merged = dict(node.attributes or {})
                for k, v in metadata.items():
                    if k in ("node_type", "universe", "volume"):
                        continue
                    merged[k] = v
                node.attributes = merged

            db.add(LoreEmbedding(
                node_id=node.id,
                universe=universe,
                volume=volume,
                chunk_text=chunk_payload,
                embedding=vector,
            ))
            await db.commit()
    except Exception as e:
        logger.error(f"commit_lore: DB write failed for {entity_name}: {e}")
        return {"committed": False, "entity_name": entity_name, "error": str(e)}

    return {"committed": True, "entity_name": entity_name}


async def report_violation(
    violation_type: str,
    character: str,
    concept: str,
    quote: str,
    tool_context: ToolContext,
) -> dict:
    """
    Logs a lore break for the Auditor to review.

    Appends a structured record to ``state["violation_log"]``. The Auditor (or
    a downstream monitoring node) can inspect this list to enforce epistemic
    or canon constraints.

    Args:
        violation_type: A short tag (e.g., 'epistemic_leak', 'anti_worf', 'canon_break').
        character: The character involved in the violation.
        concept: The forbidden concept or rule that was broken.
        quote: A direct quote from the prose that triggered the violation.
    """
    violation_type = sanitize_context(violation_type)
    character = sanitize_context(character)
    concept = sanitize_context(concept)
    quote = sanitize_context(quote)

    log = list(tool_context.state.get("violation_log", []) or [])
    log.append({
        "type": violation_type,
        "character": character,
        "concept": concept,
        "quote": quote,
    })
    tool_context.state["violation_log"] = log

    return {"logged": True, "violation_type": violation_type, "count": len(log)}




# ─── Phase C: living-Bible substrate tools ──────────────────────────────────

async def update_character_voice(
    character_name: str,
    speech_patterns: str,
    vocabulary_level: str,
    verbal_tics: list[str],
    topics_to_avoid: list[str],
    example_dialogue: str,
    tool_context: ToolContext,
) -> dict:
    """
    Persist a per-character speech profile so the Storyteller can write
    canon-faithful dialogue. Call ONCE per character per chapter when a
    character speaks, only if their existing profile is missing or stale.

    Args:
        character_name: Exact canonical character name.
        speech_patterns: Formal / casual / technical / military / archaic / etc.
        vocabulary_level: Simple / educated / specialized / archaic / modern.
        verbal_tics: Repeated phrases, filler words, mannerisms.
        topics_to_avoid: What this character deflects or refuses to discuss.
        example_dialogue: A characteristic line from this chapter.
    """
    name = sanitize_context(character_name)
    voices = dict(tool_context.state.get("character_voices") or {})
    voices[name] = {
        "speech_patterns": sanitize_context(speech_patterns),
        "vocabulary_level": sanitize_context(vocabulary_level),
        "verbal_tics": [sanitize_context(t) for t in verbal_tics],
        "topics_to_avoid": [sanitize_context(t) for t in topics_to_avoid],
        "example_dialogue": sanitize_context(example_dialogue),
    }
    tool_context.state["character_voices"] = voices
    return {"updated": True, "character": name}


async def add_pending_consequence(
    action: str,
    predicted_consequence: str,
    due_by_chapter: int,
    tool_context: ToolContext,
) -> dict:
    """
    Schedule a future consequence the Storyteller MUST address by a specific
    chapter. Used to enforce the "no effortless wins" stakes loop.

    Args:
        action: What the OC did that triggered this.
        predicted_consequence: What should happen as a result.
        due_by_chapter: Chapter by which this must resolve.
    """
    stakes = dict(tool_context.state.get("stakes_and_consequences") or {})
    pending = list(stakes.get("pending_consequences") or [])
    pending.append({
        "action": sanitize_context(action),
        "predicted_consequence": sanitize_context(predicted_consequence),
        "due_by_chapter": int(due_by_chapter),
        "overdue": False,
    })
    stakes["pending_consequences"] = pending
    # Preserve other stakes fields
    stakes.setdefault("costs_paid", [])
    stakes.setdefault("near_misses", [])
    stakes.setdefault("power_usage_debt", {})
    tool_context.state["stakes_and_consequences"] = stakes
    return {"added": True, "due_by_chapter": int(due_by_chapter)}


async def materialize_butterfly_effect(
    divergence_event_id: str,
    materialization_description: str,
    tool_context: ToolContext,
) -> dict:
    """
    Mark a previously predicted ripple from a divergence as having actually
    come true this chapter. Tracks the v1 "aim to materialize at least one
    effect every 3-4 chapters" cadence.

    Args:
        divergence_event_id: The event_id of an existing active_divergences entry.
        materialization_description: How the ripple manifested in this chapter.
    """
    target_id = sanitize_context(divergence_event_id)
    desc = sanitize_context(materialization_description)
    divs = list(tool_context.state.get("active_divergences") or [])
    matched = False
    for d in divs:
        if isinstance(d, dict) and d.get("event_id") == target_id:
            materialized = list(d.get("materialized_ripples") or [])
            materialized.append(desc)
            d["materialized_ripples"] = materialized
            matched = True
            break
    if not matched:
        # Best-effort: append a synthetic entry rather than failing.
        divs.append({
            "event_id": target_id,
            "description": "(referenced by materialize_butterfly_effect)",
            "ripple_effects": [],
            "materialized_ripples": [desc],
        })
    tool_context.state["active_divergences"] = divs
    return {"materialized": True, "event_id": target_id, "matched_existing": matched}


async def advance_event_status(
    event_name: str,
    new_status: str,
    notes: str,
    tool_context: ToolContext,
) -> dict:
    """
    Retire an upcoming canon timeline event by transitioning its status.
    Once retired, the storyteller's enforcement block stops re-injecting it.

    Args:
        event_name: The name (or event_id) of an entry in canon_timeline.events.
        new_status: One of "occurred", "modified", or "prevented".
        notes: One-line description of how it played out.
    """
    target = sanitize_context(event_name)
    notes_clean = sanitize_context(notes)
    valid_statuses = {"upcoming", "occurred", "modified", "prevented"}
    status = new_status.strip().lower()
    if status not in valid_statuses:
        status = "occurred"

    timeline = dict(tool_context.state.get("canon_timeline") or {})
    events = list(timeline.get("events") or [])
    matched = False
    for ev in events:
        if isinstance(ev, dict) and (ev.get("name") == target or ev.get("event_id") == target):
            ev["status"] = status
            if notes_clean:
                ev["notes"] = notes_clean
            matched = True
            break
    timeline["events"] = events
    tool_context.state["canon_timeline"] = timeline
    return {"retired": matched, "event": target, "new_status": status}


async def mark_knowledge_violation(
    character_name: str,
    concept_referenced: str,
    violation_type: str,
    quote: str,
    tool_context: ToolContext,
) -> dict:
    """
    Record a chapter event where a character referenced something they
    shouldn't know per knowledge_boundaries. Surfaces as a soft warning;
    does not retroactively edit the chapter.

    Args:
        character_name: Who said/thought something they shouldn't.
        concept_referenced: The forbidden concept they touched.
        violation_type: Short tag, e.g. "epistemic_leak" / "meta_break" / "future_spoiler".
        quote: A direct quote from the chapter that triggered the flag.
    """
    log = list(tool_context.state.get("violation_log") or [])
    log.append({
        "type": "knowledge_" + sanitize_context(violation_type),
        "character": sanitize_context(character_name),
        "concept": sanitize_context(concept_referenced),
        "quote": sanitize_context(quote),
    })
    tool_context.state["violation_log"] = log
    return {"logged": True, "count": len(log)}


async def mark_power_scaling_violation(
    character_name: str,
    what_happened: str,
    minimum_competence_violated: str,
    severity: str,
    tool_context: ToolContext,
) -> dict:
    """
    Record an anti-Worf breach: a protected character was written below
    their documented competence floor. Logged for downstream review and
    optionally for triggering a rewrite.

    Args:
        character_name: Protected character with an entry in canon_character_integrity.
        what_happened: Concrete description of the breach this chapter.
        minimum_competence_violated: The specific floor that was crossed.
        severity: "minor" / "moderate" / "major" / "critical".
    """
    log = list(tool_context.state.get("violation_log") or [])
    log.append({
        "type": "power_scaling",
        "character": sanitize_context(character_name),
        "what_happened": sanitize_context(what_happened),
        "minimum_competence_violated": sanitize_context(minimum_competence_violated),
        "severity": sanitize_context(severity),
    })
    tool_context.state["violation_log"] = log
    return {"logged": True, "severity": severity}


# The ADK 2.0 list of tools to provide to the ArchivistNode
ARCHIVIST_TOOLS = [
    update_relationship,
    record_divergence,
    track_power_strain,
    advance_timeline,
    commit_lore,
    report_violation,
    # Phase C substrate maintenance
    update_character_voice,
    add_pending_consequence,
    materialize_butterfly_effect,
    advance_event_status,
    mark_knowledge_violation,
    mark_power_scaling_violation,
]
