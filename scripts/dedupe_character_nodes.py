"""One-shot dedupe: collapse duplicate character lore_nodes via alias resolution.

The pre-existing lore_nodes table accumulated entity duplicates because
the archivist's commit_lore matched on exact name equality. So
"Miyuki Shiba" and "Shiba Miyuki" became two separate rows pointing at
the same character. This script:

  1. Walks every lore_node and resolves its name to a canonical form via
     src/utils/canon_aliases.resolve_alias.
  2. Groups nodes by canonical form. Groups of size 1 are skipped.
  3. For each group of duplicates: picks a survivor (preferring the node
     whose name == canonical exactly; otherwise the lowest id), merges
     attributes (union, survivor wins on conflict), repoints all
     lore_embeddings.node_id and lore_edges (source_id, target_id) at
     the survivor, then DELETEs the duplicate nodes.
  4. Walks every session and renames keys in state.active_characters and
     state.character_voices that resolve to a canonical name to use the
     canonical form, so the storyteller's voice block looks up cleanly.

Idempotent: re-running on a deduped DB is a no-op.

Usage:
    uv run python scripts/dedupe_character_nodes.py             # dry-run
    uv run python scripts/dedupe_character_nodes.py --apply
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from collections import defaultdict
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))

from sqlalchemy import delete, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.database import AsyncSessionLocal
from src.state.lore_models import LoreEdge, LoreEmbedding, LoreNode
from src.utils.canon_aliases import resolve_alias

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("dedupe_chars")


def _pick_survivor(nodes: list[LoreNode], canonical: str) -> LoreNode:
    """Among duplicates, prefer the node whose name == canonical exactly,
    else the lowest id (most stable). Caller is responsible for ensuring
    nodes is non-empty."""
    exact = [n for n in nodes if n.name == canonical]
    if exact:
        return min(exact, key=lambda n: n.id)
    return min(nodes, key=lambda n: n.id)


def _merge_attributes(survivor_attrs: dict, duplicate_attrs: dict) -> dict:
    """Survivor's existing keys win; duplicate fills only missing keys."""
    merged = dict(duplicate_attrs or {})
    merged.update(survivor_attrs or {})  # survivor overwrites
    return merged


async def _dedupe_lore_nodes(db: AsyncSession, apply: bool) -> dict[int, int]:
    """Return a {duplicate_id -> survivor_id} mapping. When apply=True,
    also performs the database mutations."""
    nodes = (await db.execute(
        select(LoreNode).where(LoreNode.node_type.in_(["character"]))
    )).scalars().all()

    by_canonical: dict[str, list[LoreNode]] = defaultdict(list)
    unresolved = 0
    for n in nodes:
        canonical = resolve_alias(n.name)
        if canonical is None:
            unresolved += 1
            continue
        by_canonical[canonical].append(n)

    logger.info("character lore_nodes: %d total, %d resolvable, %d not in alias dict",
                len(nodes), sum(len(v) for v in by_canonical.values()), unresolved)

    duplicate_to_survivor: dict[int, int] = {}
    rename_pairs: list[tuple[int, str, str]] = []  # (id, old_name, canonical)

    for canonical, group in by_canonical.items():
        if len(group) > 1:
            survivor = _pick_survivor(group, canonical)
            for dup in group:
                if dup.id == survivor.id:
                    continue
                duplicate_to_survivor[dup.id] = survivor.id
                logger.info("  MERGE: %r (id=%d) -> %r (id=%d)", dup.name, dup.id, survivor.name, survivor.id)
                if apply:
                    survivor.attributes = _merge_attributes(
                        survivor.attributes or {},
                        dup.attributes or {},
                    )
            # If the survivor's name isn't the canonical form, rename it.
            if survivor.name != canonical:
                rename_pairs.append((survivor.id, survivor.name, canonical))
        elif len(group) == 1:
            n = group[0]
            if n.name != canonical:
                rename_pairs.append((n.id, n.name, canonical))

    if apply:
        # Repoint references to duplicate nodes.
        for dup_id, surv_id in duplicate_to_survivor.items():
            await db.execute(
                update(LoreEmbedding).where(LoreEmbedding.node_id == dup_id).values(node_id=surv_id)
            )
            await db.execute(
                update(LoreEdge).where(LoreEdge.source_id == dup_id).values(source_id=surv_id)
            )
            await db.execute(
                update(LoreEdge).where(LoreEdge.target_id == dup_id).values(target_id=surv_id)
            )
        # Delete the duplicates.
        if duplicate_to_survivor:
            await db.execute(
                delete(LoreNode).where(LoreNode.id.in_(list(duplicate_to_survivor.keys())))
            )
        # Rename surviving nodes to canonical form.
        for nid, old_name, canonical in rename_pairs:
            logger.info("  RENAME: id=%d %r -> %r", nid, old_name, canonical)
            await db.execute(update(LoreNode).where(LoreNode.id == nid).values(name=canonical))
        await db.commit()
    else:
        for nid, old_name, canonical in rename_pairs:
            logger.info("  WOULD RENAME: id=%d %r -> %r", nid, old_name, canonical)

    return duplicate_to_survivor


async def _canonicalise_session_state(db: AsyncSession, apply: bool) -> None:
    """Walk session state and rename active_characters / character_voices
    keys that resolve to a canonical form. Uses raw SQL because ADK's
    sessions table is jsonb -- safer than ORM mutations.
    """
    rows = (await db.execute(text("SELECT id, state FROM sessions"))).all()
    for sid, state in rows:
        if not isinstance(state, dict):
            continue
        changes: list[str] = []
        new_state = dict(state)
        for field in ("active_characters", "character_voices"):
            d = new_state.get(field)
            if not isinstance(d, dict):
                continue
            renamed: dict = {}
            for old_key, val in d.items():
                canonical = resolve_alias(old_key)
                new_key = canonical if canonical else old_key
                if new_key in renamed:
                    # Conflict: another duplicate already wrote this canonical
                    # key. Survivor (first-written) wins to match the lore_node
                    # dedupe heuristic.
                    changes.append(f"{field}: dropped duplicate {old_key!r} (canonical {new_key!r} already present)")
                    continue
                if new_key != old_key:
                    changes.append(f"{field}: {old_key!r} -> {new_key!r}")
                renamed[new_key] = val
            new_state[field] = renamed
        if changes:
            logger.info("session %s:", sid)
            for c in changes:
                logger.info("  %s", c)
            if apply:
                await db.execute(
                    text("UPDATE sessions SET state = :s WHERE id = :sid"),
                    {"s": __import__("json").dumps(new_state), "sid": sid},
                )
    if apply:
        await db.commit()


async def main(apply: bool) -> None:
    async with AsyncSessionLocal() as db:
        merges = await _dedupe_lore_nodes(db, apply=apply)
    async with AsyncSessionLocal() as db:
        await _canonicalise_session_state(db, apply=apply)
    if apply:
        logger.info("APPLIED: %d duplicate nodes merged", len(merges))
    else:
        logger.info("DRY-RUN: %d duplicate nodes would be merged", len(merges))


def cli() -> None:
    p = argparse.ArgumentParser(description="Dedupe character lore_nodes via alias resolution.")
    p.add_argument("--apply", action="store_true", help="Actually write to DB. Default: dry-run.")
    args = p.parse_args()
    asyncio.run(main(apply=args.apply))


if __name__ == "__main__":
    cli()
