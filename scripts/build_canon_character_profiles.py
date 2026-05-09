"""One-shot: synthesise canon-faithful profiles for every canonical character
with linked corpus chunks, persist to lore_nodes.attributes and seed
state.character_voices.

This unlocks the storyteller's CHARACTER VOICES enforcement block for
characters who currently have no profile (e.g., Mari Watanabe in the live
session, who has 89 canon chunks linked but a missing voice entry).

For each canonical character node:
  1. Pull the top N canon chunks (sorted by chunk length DESC -- prefer
     substantive prose over short fragments).
  2. Concatenate as evidence and call Gemini (gemini-2.5-flash-lite for
     cost) with a structured output prompt extracting CanonProfile fields:
     personality, motivations, key_relationships, signature_scenes,
     speech_patterns, vocabulary_level, verbal_tics, example_dialogue,
     topics_to_avoid.
  3. Upsert profile into lore_nodes.attributes (preserves existing keys
     unless the new profile has stronger evidence -- new wins on conflict).
  4. Write a CharacterVoice entry (subset of CanonProfile) to every active
     session's state.character_voices, keyed by canonical name.

Skip characters with <MIN_CHUNKS canon chunks (insufficient evidence).
Idempotent: re-running upserts; --force to ignore existing attributes.

Usage:
    uv run python scripts/build_canon_character_profiles.py             # dry-run
    uv run python scripts/build_canon_character_profiles.py --apply
    uv run python scripts/build_canon_character_profiles.py --apply --limit 5 --char "Mari Watanabe"
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
from pathlib import Path
from typing import Optional

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))

from pydantic import BaseModel, Field
from sqlalchemy import select, text, update

from src.database import AsyncSessionLocal
from src.state.lore_models import LoreEmbedding, LoreNode

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("build_profiles")

# Tunables
MIN_CHUNKS = 5            # require at least this many canon chunks before profiling
MAX_CHUNKS_PER_PROFILE = 12  # how many chunks to feed Gemini per character
PROFILE_MODEL = "gemini-2.5-flash-lite"


# ─── Schema ─────────────────────────────────────────────────────────────────

class CanonProfile(BaseModel):
    """Canon-faithful character profile synthesised from corpus chunks."""

    personality: str = Field(default="", description="2-3 sentence summary of core personality")
    motivations: str = Field(default="", description="What drives this character; 1-2 sentences")
    key_relationships: list[str] = Field(
        default_factory=list,
        description="3-5 lines of form 'OtherCharacter: relationship type / dynamic'.",
    )
    signature_scenes: list[str] = Field(
        default_factory=list,
        description="2-3 iconic canon moments that define them",
    )
    speech_patterns: str = Field(
        default="",
        description="Tone, formality, register, sentence shape",
    )
    vocabulary_level: str = Field(
        default="",
        description="One of: basic / casual / advanced / technical / archaic / mixed",
    )
    verbal_tics: list[str] = Field(
        default_factory=list,
        description="Specific words/phrases they use repeatedly (e.g. 'Onii-sama')",
    )
    example_dialogue: str = Field(
        default="",
        description="ONE direct quote-style line that sounds canonically like them",
    )
    topics_to_avoid: list[str] = Field(
        default_factory=list,
        description="Subjects this character won't or shouldn't discuss in their voice",
    )


# ─── Prompt ─────────────────────────────────────────────────────────────────

_PROFILE_PROMPT_TEMPLATE = """You are analysing canonical source text for the character "{character_name}".

Below are {n_chunks} excerpts from the canonical source material in which "{character_name}" appears. Other characters may ALSO appear in these excerpts (speaking to or about "{character_name}"). Your job: synthesise a structured CanonProfile that captures how "{character_name}" is actually depicted, so a downstream storyteller can write THIS specific character in-voice.

CRITICAL CONSTRAINTS:
  1. Every field must describe "{character_name}" SPECIFICALLY. Other characters' voices and traits must NOT be attributed to them. If "{character_name}" hears Miyuki say "Onii-sama" in an excerpt, that does NOT mean "{character_name}" says "Onii-sama" -- attribute "Onii-sama" only to the speaker who actually utters it.
  2. "verbal_tics" must be SPECIFIC phrases that "{character_name}" THEMSELVES utters. If you cannot find a phrase that "{character_name}" personally repeats, leave the list empty.
  3. "example_dialogue" must be a line "{character_name}" speaks (or plausibly would speak) -- not a line another character speaks to or about them. Prefer a direct quotation from the evidence; otherwise synthesise one that matches their cadence and concerns.
  4. "speech_patterns" describes HOW "{character_name}" speaks (formal, monotone, chirpy, etc.) -- not how others speak to them.
  5. "topics_to_avoid" should reflect what canon shows: subjects "{character_name}" deflects from, refuses to discuss, or wouldn't bring up themselves.
  6. If a field has no evidence ABOUT "{character_name}" specifically, leave it empty. Empty is better than wrong attribution.

EVIDENCE:

{evidence}

Now emit a CanonProfile JSON capturing "{character_name}"'s canonical voice. Remember: only THEIR traits, not other characters'.
"""


# ─── Helpers ────────────────────────────────────────────────────────────────


async def _profileable_characters(db) -> list[tuple[int, str, int]]:
    """Return [(node_id, canonical_name, chunk_count), ...] for characters
    with >= MIN_CHUNKS linked canon chunks, sorted by chunk_count desc."""
    rows = (await db.execute(text(f"""
        SELECT n.id, n.name, count(*) as n_chunks
        FROM lore_nodes n
        JOIN lore_embeddings e ON e.node_id = n.id
        WHERE n.node_type = 'character'
          AND e.volume LIKE 'Volume %'
        GROUP BY n.id, n.name
        HAVING count(*) >= {MIN_CHUNKS}
        ORDER BY n_chunks DESC
    """))).all()
    return [(r.id, r.name, r.n_chunks) for r in rows]


async def _fetch_chunks(db, node_id: int, limit: int) -> list[str]:
    """Top chunks for a character, sorted by length desc (prefer substantive
    prose over short fragments). Length is a decent proxy for content density
    in this corpus."""
    rows = (await db.execute(text(f"""
        SELECT chunk_text
        FROM lore_embeddings
        WHERE node_id = :nid AND volume LIKE 'Volume %'
        ORDER BY char_length(chunk_text) DESC
        LIMIT {limit}
    """), {"nid": node_id})).all()
    return [r.chunk_text for r in rows]


def _format_evidence(chunks: list[str]) -> str:
    blocks = []
    for i, c in enumerate(chunks, 1):
        blocks.append(f"--- Chunk {i} ---\n{c.strip()}\n")
    return "\n".join(blocks)


async def _build_profile(client, character_name: str, chunks: list[str]) -> Optional[CanonProfile]:
    """One Gemini call per character. Returns None on failure."""
    from google.genai import types
    prompt = _PROFILE_PROMPT_TEMPLATE.format(
        character_name=character_name,
        n_chunks=len(chunks),
        evidence=_format_evidence(chunks),
    )
    try:
        resp = await client.aio.models.generate_content(
            model=PROFILE_MODEL,
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=CanonProfile,
                max_output_tokens=2048,
            ),
        )
        return CanonProfile.model_validate_json(resp.text or "{}")
    except Exception as e:
        logger.warning("profile build failed for %r: %s", character_name, e)
        return None


def _voice_subset(profile: CanonProfile) -> dict:
    """Subset of CanonProfile that maps to state.character_voices entries."""
    return {
        "speech_patterns": profile.speech_patterns,
        "vocabulary_level": profile.vocabulary_level,
        "verbal_tics": list(profile.verbal_tics),
        "topics_to_avoid": list(profile.topics_to_avoid),
        "example_dialogue": profile.example_dialogue,
    }


# ─── Main ───────────────────────────────────────────────────────────────────

async def main(apply: bool, limit: Optional[int], only_char: Optional[str], force: bool) -> None:
    api_key = os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY")
    if not api_key:
        logger.error("Missing GOOGLE_API_KEY / GEMINI_API_KEY env var")
        return
    from google import genai
    client = genai.Client(api_key=api_key)

    async with AsyncSessionLocal() as db:
        candidates = await _profileable_characters(db)

    if only_char:
        candidates = [c for c in candidates if c[1] == only_char]
        logger.info("filter --char=%r: %d match(es)", only_char, len(candidates))
    if limit is not None:
        candidates = candidates[:limit]

    logger.info("will profile %d character(s) (model=%s)", len(candidates), PROFILE_MODEL)

    for node_id, name, chunk_count in candidates:
        async with AsyncSessionLocal() as db:
            existing_node = (await db.execute(
                select(LoreNode).where(LoreNode.id == node_id)
            )).scalar_one()
            if existing_node.attributes and not force:
                # Heuristic: if attributes already has 'personality' and
                # 'speech_patterns', treat as already profiled and skip.
                attrs = existing_node.attributes
                if isinstance(attrs, dict) and attrs.get("personality") and attrs.get("speech_patterns"):
                    logger.info("[skip] %r already profiled (use --force to overwrite)", name)
                    continue

            chunks = await _fetch_chunks(db, node_id, MAX_CHUNKS_PER_PROFILE)
        logger.info("[%s] %d chunks", name, len(chunks))

        profile = await _build_profile(client, name, chunks)
        if profile is None:
            continue

        logger.info("  -> personality: %s", (profile.personality or "")[:120])
        logger.info("  -> verbal_tics: %s", profile.verbal_tics)
        logger.info("  -> example: %s", (profile.example_dialogue or "")[:140])

        if not apply:
            continue

        # Upsert lore_nodes.attributes (merge: profile fields + existing keys preserved)
        async with AsyncSessionLocal() as db:
            n = (await db.execute(select(LoreNode).where(LoreNode.id == node_id))).scalar_one()
            existing_attrs = dict(n.attributes or {})
            new_attrs = {**existing_attrs, **profile.model_dump(mode="json")}
            await db.execute(update(LoreNode).where(LoreNode.id == node_id).values(attributes=new_attrs))
            await db.commit()

        # Seed state.character_voices in every session for which this
        # character is active or already voice-tracked. Don't overwrite a
        # non-empty existing voice profile.
        voice = _voice_subset(profile)
        async with AsyncSessionLocal() as db:
            sess_rows = (await db.execute(text("SELECT id, state FROM sessions"))).all()
            for sid, state in sess_rows:
                if not isinstance(state, dict):
                    continue
                actives = state.get("active_characters") or {}
                voices = state.get("character_voices") or {}
                if name not in actives and name not in voices:
                    continue  # not relevant to this session
                if voices.get(name):
                    # Already populated -- skip unless --force
                    if not force:
                        continue
                voices[name] = voice
                state = dict(state)
                state["character_voices"] = voices
                await db.execute(
                    text("UPDATE sessions SET state = :s WHERE id = :sid"),
                    {"s": json.dumps(state), "sid": sid},
                )
            await db.commit()

    logger.info("DONE")


def cli() -> None:
    p = argparse.ArgumentParser(description="Build canon-faithful character profiles.")
    p.add_argument("--apply", action="store_true", help="Actually write to DB. Default: dry-run.")
    p.add_argument("--limit", type=int, default=None, help="Max characters to profile.")
    p.add_argument("--char", type=str, default=None, help="Profile only this canonical name.")
    p.add_argument("--force", action="store_true", help="Overwrite existing profiles / voices.")
    args = p.parse_args()
    asyncio.run(main(apply=args.apply, limit=args.limit, only_char=args.char, force=args.force))


if __name__ == "__main__":
    cli()
