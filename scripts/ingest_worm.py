"""Ingest scraped Worm text (data/worm/Arc-XX-Name.txt) into the lore DB.

Pipeline:
  1. For each Arc-XX-Name.txt file:
     a. Skip if source_text already has a row for this universe+volume
        (idempotent re-run).
     b. INSERT source_text(universe='worm', volume='Arc XX - Name',
        content=<text>, word_count=<count>).
     c. Chunk via src.utils.chunking.chunk_text (1000-char chunks,
        150 overlap).
     d. Embed each chunk via Ollama (parallel batches of 16).
     e. INSERT lore_embeddings rows (universe, volume, chunk_text,
        embedding) -- node_id NULL until Phase B backfill links them.

Mirrors the existing LoreIngestionNode pattern (src/nodes/lore_ingestion.py)
but as a standalone CLI rather than an ADK node, so it can be run from
the shell against the scraped output without spinning up the workflow.

Usage:
    uv run python scripts/ingest_worm.py             # dry-run
    uv run python scripts/ingest_worm.py --apply
    uv run python scripts/ingest_worm.py --apply --arc 1   # one arc only
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import re
import sys
import time
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.database import AsyncSessionLocal
from src.services.embedding_service import get_embedding
from src.state.lore_models import LoreEmbedding, SourceText
from src.utils.chunking import chunk_text

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("ingest_worm")

DATA_DIR = _PROJECT_ROOT / "data" / "worm"
INGEST_BATCH_SIZE = 16

# Arc-XX-Name.txt -> "Arc XX - Name"
_FILENAME_RE = re.compile(r"^Arc-(\d{2})-(.+)\.txt$")


def _volume_label(filename: str) -> str | None:
    """Filename -> human "Arc XX - Name" volume tag. None for non-arc files."""
    m = _FILENAME_RE.match(filename)
    if not m:
        return None
    arc_num = m.group(1)
    arc_name = m.group(2).replace("-", " ")
    return f"Arc {arc_num} - {arc_name}"


async def _already_ingested(db: AsyncSession, volume: str) -> bool:
    """Skip arcs already in source_text. Re-run is safe."""
    stmt = select(SourceText.id).where(
        SourceText.universe == "worm", SourceText.volume == volume
    )
    return (await db.execute(stmt)).scalar_one_or_none() is not None


async def _ingest_arc(text: str, volume: str, apply: bool) -> tuple[int, int]:
    """Ingest one arc. Returns (chunks_persisted, chunks_failed)."""
    chunks = chunk_text(text)
    total = len(chunks)
    word_count = len(text.split())

    if not apply:
        logger.info("  [dry-run] would persist 1 source_text row, %d chunks (%d words)",
                    total, word_count)
        return total, 0

    # Persist source_text row first (transactional with chunks below).
    async with AsyncSessionLocal() as db:
        st = SourceText(
            universe="worm",
            volume=volume,
            content=text,
            word_count=word_count,
        )
        db.add(st)
        await db.commit()
    logger.info("  [+] source_text row persisted (%d words)", word_count)

    # Chunk + embed + persist in batches. Same shape as LoreIngestionNode.
    persisted = 0
    failed = 0
    for batch_start in range(0, total, INGEST_BATCH_SIZE):
        batch = chunks[batch_start : batch_start + INGEST_BATCH_SIZE]
        results = await asyncio.gather(
            *(get_embedding(c) for c in batch),
            return_exceptions=True,
        )
        async with AsyncSessionLocal() as db:
            for chunk, vector in zip(batch, results):
                if isinstance(vector, BaseException):
                    failed += 1
                    logger.warning("    embed failed for chunk in %s: %s", volume, vector)
                    continue
                db.add(LoreEmbedding(
                    universe="worm",
                    volume=volume,
                    chunk_text=chunk,
                    embedding=vector,
                ))
                persisted += 1
            await db.commit()
        if (batch_start // INGEST_BATCH_SIZE) % 5 == 0:
            logger.info("    persisted %d/%d (failed %d)", persisted, total, failed)

    logger.info("  [done] persisted %d/%d chunks (failed %d)", persisted, total, failed)
    return persisted, failed


async def main(apply: bool, only_arc: int | None) -> None:
    if not DATA_DIR.exists():
        logger.error("data dir missing: %s -- run scrape_worm.py first", DATA_DIR)
        return

    txt_files = sorted(DATA_DIR.glob("Arc-*.txt"))
    logger.info("found %d arc files in %s", len(txt_files), DATA_DIR)

    if only_arc is not None:
        txt_files = [f for f in txt_files if f.name.startswith(f"Arc-{only_arc:02d}-")]
        logger.info("filter --arc=%d: %d match(es)", only_arc, len(txt_files))

    t0 = time.monotonic()
    total_chunks = 0
    total_failed = 0

    for path in txt_files:
        volume = _volume_label(path.name)
        if volume is None:
            continue
        logger.info("ARC: %s (file=%s)", volume, path.name)

        text = path.read_text(encoding="utf-8")
        if not text.strip():
            logger.warning("  empty file, skipping")
            continue

        if apply:
            async with AsyncSessionLocal() as db:
                if await _already_ingested(db, volume):
                    logger.info("  [skip] already ingested for universe='worm'")
                    continue

        persisted, failed = await _ingest_arc(text, volume, apply)
        total_chunks += persisted
        total_failed += failed

    elapsed = time.monotonic() - t0
    if apply:
        logger.info(
            "DONE in %.1fs: %d chunks persisted across %d arcs (failed %d)",
            elapsed, total_chunks, len(txt_files), total_failed,
        )
    else:
        logger.info("DRY-RUN done in %.1fs (no DB writes)", elapsed)


def cli() -> None:
    p = argparse.ArgumentParser(description="Ingest scraped Worm into lore DB.")
    p.add_argument("--apply", action="store_true", help="Actually write. Default: dry-run.")
    p.add_argument("--arc", type=int, default=None, help="Ingest only this arc number.")
    args = p.parse_args()
    asyncio.run(main(apply=args.apply, only_arc=args.arc))


if __name__ == "__main__":
    cli()
