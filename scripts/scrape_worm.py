"""Scrape Worm by Wildbow from parahumans.wordpress.com into per-arc plain
text files under data/worm/.

Pipeline downstream:
  1. This script -> data/worm/Arc-XX-Name.txt
  2. scripts/ingest_worm.py -> source_text + lore_embeddings (NULL node_id)
  3. Update src/utils/canon_aliases.py with Worm cast (W3 task)
  4. scripts/backfill_canon_chunk_entities.py --apply -> entity links
  5. scripts/build_canon_character_profiles.py --apply -> profiles + voices

Idempotent: chapters already on disk are skipped. Polite to the host:
2 concurrent requests max, 0.5s delay between batches.

Usage:
    uv run python scripts/scrape_worm.py             # full scrape (~1500 chapters? no: ~258)
    uv run python scripts/scrape_worm.py --limit 10  # first 10 chapters only (smoke)
    uv run python scripts/scrape_worm.py --arc 1     # only Arc 1 (test)
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import re
import sys
from dataclasses import dataclass
from pathlib import Path

import httpx
from bs4 import BeautifulSoup

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("scrape_worm")

TOC_URL = "https://parahumans.wordpress.com/table-of-contents/"
DATA_DIR = _PROJECT_ROOT / "data" / "worm"
USER_AGENT = "Mozilla/5.0 (research/RAG) fable2.0 worm-ingestion"

# parahumans is a personal wordpress; be polite
CONCURRENCY = 2
INTER_BATCH_DELAY_SEC = 0.5


@dataclass
class Chapter:
    arc_num: int            # 1..30
    arc_name: str           # "Gestation"
    chapter_id: str         # "1.01" / "1.x"
    url: str

    @property
    def filename(self) -> str:
        # Sortable: 1.01 -> "1-01", interlude "1.x" -> "1-z" so it sorts last
        ch = self.chapter_id.replace(".", "-")
        if ch.endswith("-x"):
            ch = ch.replace("-x", "-z-interlude")
        return ch


@dataclass
class Arc:
    arc_num: int
    arc_name: str
    chapters: list[Chapter]

    @property
    def filename(self) -> str:
        # "Arc-01-Gestation.txt"
        clean_name = re.sub(r"[^\w]+", "-", self.arc_name).strip("-")
        return f"Arc-{self.arc_num:02d}-{clean_name}.txt"


# ─── TOC parsing ────────────────────────────────────────────────────────────

# Worm has two TOC URL formats:
#   Arcs 1-10:   /category/stories-arcs-1-10/arc-N-name/N-MM/
#                or with %c2%ad soft-hyphen prefix on Arc 10:
#                /category/stories-arcs-1-10/%c2%ad-arc-10-parasite/10-1/
#   Arcs 11-30:  /YYYY/MM/DD/<arc-slug>-N-M/   (e.g. /2013/06/29/scarab-25-1/)
#                /YYYY/MM/DD/interlude-N(-suffix)?/  for interludes
#   Epilogue:    /YYYY/MM/DD/teneral-e-N/

# Pattern A: arcs 1-10 by category. Tolerates any extra path segment between
# the stories-arcs-X-Y/ and the arc-N-slug/ part (handles %c2%ad-arc-10-...).
_PAT_CATEGORY = re.compile(
    r"/arc-(\d+)-([\w-]+?)/(\d+[-.]\w+(?:-\w+)*)/?$"
)
# Pattern B: arcs 11-30 by date-based permalink slug.
#   (slug)-N-M  or  interlude-N(-anything)?
_PAT_DATED_CHAPTER = re.compile(
    r"/\d{4}/\d{2}/\d{2}/([\w-]+?)-(\d+)-(\d+)/?$"
)
_PAT_DATED_INTERLUDE = re.compile(
    r"/\d{4}/\d{2}/\d{2}/interlude-(\d+)(?:-[\w-]+)?/?$"
)
# Epilogue
_PAT_TENERAL = re.compile(
    r"/\d{4}/\d{2}/\d{2}/teneral-e-(\d+)/?$"
)

# Arc number -> canonical name. Arcs 1-10 are derived from category URL slug;
# arcs 11-30 + epilogue come from this hardcoded list (the date-based slug
# only contains the arc-name-slug, so we map it explicitly).
_ARC_NAMES: dict[int, str] = {
    1: "Gestation", 2: "Insinuation", 3: "Agitation", 4: "Shell",
    5: "Hive", 6: "Tangle", 7: "Buzz", 8: "Extermination",
    9: "Sentinel", 10: "Parasite", 11: "Infestation", 12: "Plague",
    13: "Snare", 14: "Prey", 15: "Colony", 16: "Monarch",
    17: "Migration", 18: "Queen", 19: "Extinction", 20: "Chrysalis",
    21: "Imago", 22: "Cell", 23: "Drone", 24: "Crushed",
    25: "Scarab", 26: "Sting", 27: "Extinction-II", 28: "Torch",
    29: "Venom", 30: "Speck", 99: "Teneral",  # 99 = epilogue sentinel
}


def _normalise_chapter_id(arc: int, chap_part: str) -> str:
    """1-01 -> '1.01'; 1-x-interlude -> '1.x'; '25-1' -> '25.1'."""
    if "x" in chap_part:
        return f"{arc}.x"
    parts = chap_part.replace(".", "-").split("-")
    if len(parts) >= 2:
        return f"{parts[0]}.{parts[1]}"
    return chap_part


def parse_toc(html: str) -> list[Arc]:
    """Walk the TOC and group every chapter link by arc.

    Handles three URL formats: category-based (arcs 1-10), date-based
    chapter (arcs 11-30 + epilogue), and date-based interlude. Falls
    through silently for non-chapter links (sidebar, comments).
    """
    soup = BeautifulSoup(html, "html.parser")
    chapters: dict[int, Arc] = {}
    seen_urls: set[str] = set()

    for a in soup.find_all("a", href=True):
        href = a["href"]
        if href in seen_urls:
            continue

        arc_num: int | None = None
        chapter_id: str | None = None

        # Pattern A: arcs 1-10 category URL
        m = _PAT_CATEGORY.search(href)
        if m:
            arc_num = int(m.group(1))
            chap_part = m.group(3)
            chapter_id = _normalise_chapter_id(arc_num, chap_part)

        # Pattern B: arcs 11-30 dated chapter
        if arc_num is None:
            m = _PAT_DATED_CHAPTER.search(href)
            if m:
                # Slug includes arc-name (we ignore -- name comes from _ARC_NAMES)
                arc_num = int(m.group(2))
                chapter_id = f"{arc_num}.{int(m.group(3))}"

        # Pattern C: dated interlude
        if arc_num is None:
            m = _PAT_DATED_INTERLUDE.search(href)
            if m:
                arc_num = int(m.group(1))
                chapter_id = f"{arc_num}.x"

        # Pattern D: epilogue (Teneral E.N) -> arc 99
        if arc_num is None:
            m = _PAT_TENERAL.search(href)
            if m:
                arc_num = 99
                chapter_id = f"E.{int(m.group(1))}"

        if arc_num is None or chapter_id is None:
            continue
        seen_urls.add(href)

        arc_name = _ARC_NAMES.get(arc_num, f"Arc-{arc_num}")
        if arc_num not in chapters:
            chapters[arc_num] = Arc(arc_num=arc_num, arc_name=arc_name, chapters=[])
        chapters[arc_num].chapters.append(
            Chapter(arc_num=arc_num, arc_name=arc_name, chapter_id=chapter_id, url=href)
        )

    arcs = sorted(chapters.values(), key=lambda a: a.arc_num)
    for arc in arcs:
        arc.chapters.sort(key=lambda c: (c.chapter_id.endswith(".x"), c.chapter_id))
    return arcs


# ─── Chapter content extraction ─────────────────────────────────────────────


def extract_chapter_text(html: str) -> str:
    """Return the cleaned prose of one Worm chapter.

    parahumans uses standard wordpress markup: the post body lives in
    <div class="entry-content">. We strip the prev/next nav anchors at
    head/foot, drop wordpress sharing/comments widgets, and keep paragraph
    breaks as \\n\\n so chunk_text() splits cleanly downstream.
    """
    soup = BeautifulSoup(html, "html.parser")
    entry = soup.find(class_="entry-content")
    if entry is None:
        return ""

    # Strip Wordpress-injected widgets that aren't story prose:
    # - Sharing buttons (.sharedaddy, #jp-post-flair)
    # - Comment forms / lists
    # - Embedded ads / related-posts blocks
    for selector in [
        ".sharedaddy",
        "#jp-post-flair",
        ".sd-sharing-enabled",
        ".jp-relatedposts",
        ".wpcnt",
        "script",
        "style",
    ]:
        for el in entry.select(selector):
            el.decompose()

    # Remove "Previous Chapter" / "Next Chapter" nav anchors. These usually
    # live in <p> tags right at the start and end of the content.
    nav_re = re.compile(r"^(previous|next)\s+chapter", re.IGNORECASE)
    for p in entry.find_all("p"):
        text = p.get_text(strip=True)
        if nav_re.match(text) and len(text) < 80:
            p.decompose()

    # Get paragraphs as separate blocks; preserves \n\n boundaries that
    # the project's chunk_text() relies on.
    paragraphs = []
    for p in entry.find_all(["p", "blockquote", "h1", "h2", "h3", "h4"]):
        text = p.get_text(separator=" ", strip=True)
        if not text:
            continue
        # Skip pure nav fragments that survived
        if len(text) < 30 and ("chapter" in text.lower() and ("next" in text.lower() or "previous" in text.lower())):
            continue
        paragraphs.append(text)

    return "\n\n".join(paragraphs)


# ─── Async fetch with concurrency cap ───────────────────────────────────────


async def fetch(client: httpx.AsyncClient, url: str, retries: int = 3) -> str:
    last_exc: Exception | None = None
    for attempt in range(retries):
        try:
            r = await client.get(url, follow_redirects=True, timeout=30.0)
            r.raise_for_status()
            return r.text
        except (httpx.HTTPError, httpx.TimeoutException) as e:
            last_exc = e
            await asyncio.sleep(2 ** attempt)
    raise last_exc or RuntimeError(f"fetch failed: {url}")


async def download_chapter(
    client: httpx.AsyncClient,
    sem: asyncio.Semaphore,
    chapter: Chapter,
) -> tuple[Chapter, str]:
    async with sem:
        try:
            html = await fetch(client, chapter.url)
        except Exception as e:
            logger.warning("fetch failed for %s: %s", chapter.chapter_id, e)
            return chapter, ""
        await asyncio.sleep(INTER_BATCH_DELAY_SEC / CONCURRENCY)
        return chapter, extract_chapter_text(html)


# ─── Main pipeline ──────────────────────────────────────────────────────────


async def main(only_arc: int | None, limit: int | None) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    headers = {"User-Agent": USER_AGENT}
    async with httpx.AsyncClient(headers=headers) as client:
        logger.info("fetching TOC: %s", TOC_URL)
        toc_html = await fetch(client, TOC_URL)
        arcs = parse_toc(toc_html)
        total_chapters = sum(len(a.chapters) for a in arcs)
        logger.info("TOC parsed: %d arcs, %d chapters total", len(arcs), total_chapters)

        if only_arc is not None:
            arcs = [a for a in arcs if a.arc_num == only_arc]
            logger.info("filter --arc=%d: %d arcs match", only_arc, len(arcs))

        sem = asyncio.Semaphore(CONCURRENCY)
        for arc in arcs:
            arc_path = DATA_DIR / arc.filename
            if arc_path.exists() and not limit:
                logger.info("[skip] %s (already exists at %s)", arc.arc_name, arc_path.name)
                continue

            chapters_to_fetch = arc.chapters
            if limit is not None:
                chapters_to_fetch = chapters_to_fetch[:limit]
            logger.info("ARC %d: %s -- fetching %d chapters",
                        arc.arc_num, arc.arc_name, len(chapters_to_fetch))

            tasks = [download_chapter(client, sem, ch) for ch in chapters_to_fetch]
            results = await asyncio.gather(*tasks)
            sections = []
            for ch, text in results:
                if not text:
                    logger.warning("  empty chapter: %s (%s)", ch.chapter_id, ch.url)
                    continue
                sections.append(f"## Chapter {ch.chapter_id}\n\n{text}")
                logger.info("  ch %s: %d chars", ch.chapter_id, len(text))

            if not sections:
                logger.warning("[skip] arc %d empty (no chapters scraped)", arc.arc_num)
                continue

            arc_text = (
                f"# Arc {arc.arc_num}: {arc.arc_name}\n\n"
                + "\n\n".join(sections)
            )
            arc_path.write_text(arc_text, encoding="utf-8")
            logger.info("[wrote] %s (%d chars, %d chapters)",
                        arc_path.name, len(arc_text), len(sections))

            if limit is not None:
                break  # smoke mode: stop after one arc

    logger.info("DONE -- output dir: %s", DATA_DIR)


def cli() -> None:
    p = argparse.ArgumentParser(description="Scrape Worm from parahumans.wordpress.com")
    p.add_argument("--arc", type=int, default=None, help="Only fetch this arc number (smoke).")
    p.add_argument("--limit", type=int, default=None, help="Limit chapters per arc (smoke).")
    args = p.parse_args()
    asyncio.run(main(only_arc=args.arc, limit=args.limit))


if __name__ == "__main__":
    cli()
