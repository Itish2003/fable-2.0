"""One-shot backfill: link the 8087 canonical Volume chunks to entity nodes.

Background: the lore_embeddings table holds 8087 chunks of canonical Mahouka
volumes (Vol 01-32 + side stories) with `node_id = NULL`. The embeddings
were ingested without an entity-extraction pass, so retrieve_lore() can't
find chunks BY entity -- it can only find chunks by raw text similarity,
which is unreliable (the model's embedding produces high-similarity vectors
for short runtime shells like "Shiba Miyuki {}" relative to genuine prose).

This script:
  1. Loads the canonical character + alias dict (src/utils/canon_aliases.py).
  2. Builds an in-memory map of existing lore_node names -> canonical name
     (via alias resolution), so we reuse existing duplicates rather than
     creating a 3rd copy. The dedupe phase (C) collapses duplicates separately.
  3. Iterates lore_embeddings rows with NULL node_id, runs primary_entity()
     on each chunk_text, and UPDATEs node_id to the canonical entity's node.
     Creates the canonical node on first reference (UPSERT by name).
  4. Reports a coverage summary.

Idempotent (safe to re-run): only touches rows with NULL node_id, so
already-linked chunks are skipped on subsequent runs.

Usage:
    uv run python scripts/backfill_canon_chunk_entities.py             # dry-run by default
    uv run python scripts/backfill_canon_chunk_entities.py --apply     # actually write
    uv run python scripts/backfill_canon_chunk_entities.py --apply --limit 100   # B3 sample
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from collections import Counter
from pathlib import Path

# Allow `uv run python scripts/foo.py` from any cwd: prepend project root.
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.database import AsyncSessionLocal
from src.state.lore_models import LoreEmbedding, LoreNode
from src.utils.canon_aliases import primary_entity, resolve_alias

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("backfill_canon")


async def _build_existing_node_map(db: AsyncSession) -> dict[str, int]:
    """canonical_name -> existing_node_id, derived from current lore_nodes.

    Walks every lore_node, runs alias resolution on its name. If multiple
    nodes resolve to the same canonical (the duplicate case), prefer the
    one whose name IS the canonical form. The dedupe phase (C) handles
    the actual merge/delete; we just need a stable lookup here.
    """
    rows = (await db.execute(select(LoreNode.id, LoreNode.name))).all()
    canonical_to_node: dict[str, int] = {}
    for nid, name in rows:
        canonical = resolve_alias(name)
        if canonical is None:
            continue
        existing = canonical_to_node.get(canonical)
        if existing is None:
            canonical_to_node[canonical] = nid
        else:
            # Prefer the node whose name == canonical exactly.
            existing_name = next((n for i, n in rows if i == existing), None)
            if name == canonical:
                canonical_to_node[canonical] = nid
            elif existing_name == canonical:
                pass  # keep the existing canonical-named one
            # else: keep the first-seen; dedupe will sort it out
    return canonical_to_node


async def _ensure_node(
    db: AsyncSession,
    canonical_name: str,
    cache: dict[str, int],
    apply: bool,
) -> int:
    """Return the lore_node.id for ``canonical_name``. Creates the node
    if missing. ``cache`` is the canonical_to_node map and is updated in
    place. When ``apply=False`` (dry-run), creates an in-memory placeholder
    id (-1, -2, ...) so the script can proceed without writes.
    """
    if canonical_name in cache:
        return cache[canonical_name]
    if not apply:
        # Dry-run placeholder: negative ids don't collide with real ones.
        placeholder = -(len(cache) + 1)
        cache[canonical_name] = placeholder
        return placeholder
    node = LoreNode(name=canonical_name, node_type="character", attributes={})
    db.add(node)
    await db.flush()  # populate node.id without committing the txn
    cache[canonical_name] = node.id
    return node.id


async def main(apply: bool, limit: int | None) -> None:
    async with AsyncSessionLocal() as db:
        existing_map = await _build_existing_node_map(db)
        logger.info("loaded %d existing canonical -> node_id mappings", len(existing_map))

        # Pull all unlinked canon chunks (volume LIKE 'Volume %' is the
        # canonical-corpus marker; archivist_runtime / chapter_summaries
        # have node_ids already so we skip them implicitly via node_id NULL).
        stmt = (
            select(LoreEmbedding.id, LoreEmbedding.chunk_text)
            .where(LoreEmbedding.node_id.is_(None))
            .where(LoreEmbedding.volume.like("Volume %"))
        )
        if limit is not None:
            stmt = stmt.limit(limit)
        rows = (await db.execute(stmt)).all()
        logger.info("scanning %d unlinked canon chunks (limit=%s)", len(rows), limit)

        cache = dict(existing_map)
        nodes_created = 0
        nodes_pre_cache_size = len(cache)
        per_entity = Counter()
        unlinked = 0

        # Build the list of (chunk_id, target_node_id) updates.
        update_pairs: list[tuple[int, int]] = []
        for chunk_id, chunk_text in rows:
            entity = primary_entity(chunk_text)
            if entity is None:
                unlinked += 1
                continue
            node_id = await _ensure_node(db, entity, cache, apply)
            update_pairs.append((chunk_id, node_id))
            per_entity[entity] += 1

        nodes_created = len(cache) - nodes_pre_cache_size

        if apply:
            # Batch-update: one UPDATE per chunk is fine for 8087 rows in
            # a single transaction; SQLAlchemy batches them efficiently.
            for chunk_id, node_id in update_pairs:
                await db.execute(
                    update(LoreEmbedding)
                    .where(LoreEmbedding.id == chunk_id)
                    .values(node_id=node_id)
                )
            await db.commit()
            logger.info("APPLIED: %d chunk updates committed, %d new nodes created",
                        len(update_pairs), nodes_created)
        else:
            logger.info("DRY-RUN: would update %d chunks and create %d new nodes",
                        len(update_pairs), nodes_created)

        # Coverage summary
        total_scanned = len(rows)
        linked = len(update_pairs)
        coverage = (linked / total_scanned * 100) if total_scanned else 0.0
        logger.info("coverage: linked %d / %d (%.1f%%); unlinked (no canon entity detected): %d",
                    linked, total_scanned, coverage, unlinked)
        logger.info("top 20 entities by linked chunks:")
        for name, n in per_entity.most_common(20):
            logger.info("  %-30s %4d", name, n)


def cli() -> None:
    p = argparse.ArgumentParser(description="Backfill node_id on canon chunks via alias matching.")
    p.add_argument("--apply", action="store_true", help="Actually write to DB. Default: dry-run.")
    p.add_argument("--limit", type=int, default=None, help="Limit chunks scanned (for sampling).")
    args = p.parse_args()
    asyncio.run(main(apply=args.apply, limit=args.limit))


if __name__ == "__main__":
    cli()
