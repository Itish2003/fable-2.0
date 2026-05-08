"""Phase G: source-universe leakage guard.

Catches when source-universe terminology appears in prose where it
doesn't belong (e.g. "Cursed Energy" in a non-JJK story). Used by the
auditor as a soft warning — it does not block the chapter, just flags
it in violation_log so the archivist + author know to clean up.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable

# Keyed by short universe slug. Each list contains terms that should NEVER
# appear in a story whose universes do NOT include this slug.
LEAKAGE_TERMS: dict[str, list[str]] = {
    "jjk": [
        "cursed technique",
        "cursed energy",
        "domain expansion",
        "reverse cursed technique",
        "binding vow",
        "innate domain",
        "ten shadows",
    ],
    "worm": [
        "shard",
        "trigger event",
        "queen administrator",
        "cauldron vials",
        "parahuman response team",
        "manton limit",
        "endbringer",
    ],
    "marvel": [
        "infinity stone",
        "quantum realm",
        "darkforce",
        "extremis",
        "vibranium",
        "arc reactor",
    ],
    "mahouka": [
        "psion",
        "pushion",
        "cad",
        "magic high school",
        "ten master clans",
        "weed",
        "bloom",
    ],
    "naruto": [
        "chakra",
        "sharingan",
        "byakugan",
        "rasengan",
        "kage bunshin",
        "tailed beast",
    ],
    "dragonball": [
        "ki blast",
        "kamehameha",
        "super saiyan",
        "saiyan",
        "instant transmission",
    ],
}

# Map free-form universe titles -> the short slug used as a LEAKAGE_TERMS key.
_UNIVERSE_ALIASES: dict[str, str] = {
    "jujutsu kaisen": "jjk",
    "worm": "worm",
    "wormverse": "worm",
    "marvel": "marvel",
    "mcu": "marvel",
    "the irregular at magic high school": "mahouka",
    "mahouka koukou no rettousei": "mahouka",
    "mahouka": "mahouka",
    "naruto": "naruto",
    "boruto": "naruto",
    "dragon ball": "dragonball",
    "dragon ball z": "dragonball",
    "dbz": "dragonball",
}


def normalize_universes(story_universes: Iterable[str]) -> set[str]:
    """Map free-form story universe titles to LEAKAGE_TERMS slugs."""
    out: set[str] = set()
    for u in story_universes or []:
        key = (u or "").strip().lower()
        if not key:
            continue
        if key in _UNIVERSE_ALIASES:
            out.add(_UNIVERSE_ALIASES[key])
            continue
        # Substring fallback: aliases that appear inside a longer title.
        for alias, slug in _UNIVERSE_ALIASES.items():
            if alias in key:
                out.add(slug)
                break
    return out


@dataclass
class Leak:
    """A single detected leakage hit."""
    universe_origin: str  # the slug whose term was matched (e.g. "jjk")
    term: str             # the offending term (lower-case canonical form)
    quote: str            # surrounding context, capped at ~120 chars

    def to_dict(self) -> dict:
        return {
            "type": "source_universe_leakage",
            "origin_universe": self.universe_origin,
            "term": self.term,
            "quote": self.quote,
        }


def detect_leakage(text: str, story_universes: Iterable[str]) -> list[Leak]:
    """Return leakage hits where a term from a universe NOT in story_universes appears.

    Case-insensitive whole-word match (Unicode-aware regex). Multiple
    occurrences of the same term collapse into one hit.
    """
    if not text:
        return []
    lower = text.lower()
    in_story = normalize_universes(story_universes)
    seen: set[tuple[str, str]] = set()
    hits: list[Leak] = []
    for slug, terms in LEAKAGE_TERMS.items():
        if slug in in_story:
            continue
        for term in terms:
            pattern = re.compile(rf"\b{re.escape(term)}\b", re.IGNORECASE)
            m = pattern.search(lower)
            if not m:
                continue
            key = (slug, term)
            if key in seen:
                continue
            seen.add(key)
            start = max(0, m.start() - 40)
            end = min(len(text), m.end() + 40)
            quote = text[start:end].replace("\n", " ").strip()
            if start > 0:
                quote = "…" + quote
            if end < len(text):
                quote = quote + "…"
            hits.append(Leak(universe_origin=slug, term=term, quote=quote))
    return hits
