"""Canonical arc → date-range + content map for each seeded universe.

Used by the storyteller's ARC CONTEXT block. Given the story's
``current_timeline_date``, locate the canonical arc in the matching
universe and emit:
  - what's happening canonically at this point (events the world is
    "supposed to" be experiencing)
  - what the OC plausibly knows (public information at this date)
  - what the OC does NOT know (canon-blind information)

This data is hand-curated for each canonical universe we've seeded.
The corpus is also entity-and-volume-linked, so future improvements
can supplement these hard-coded summaries with retrieved chunks from
the matching arc volumes — but the hard-coded tier provides reliable
baseline coverage.

Adding a new universe: add a new entry to ``CANON_ARCS`` with
``(start_year, start_month, end_year, end_month)`` ranges and the
narrative payload.
"""

from __future__ import annotations

import re
from typing import Optional

# (start_year, start_month_or_0, end_year, end_month_or_0)
# Use 0 if a boundary is not yet known; 0 in start_month means "anytime
# in start_year"; 0 in end_month means "rest of end_year".
ArcRange = tuple[int, int, int, int]


# ─── Worm by Wildbow (canonical timeline: April 2011 — late 2011) ──────────────
#
# Worm's arcs are tightly date-attested. These ranges align with the corpus
# volumes and the canonical event chronology.
_WORM_ARCS: list[dict] = [
    {
        "name": "Arc 1: Gestation",
        "range": (2011, 4, 2011, 4),
        "canon_events": [
            "Taylor Hebert's trigger event has just occurred (locker incident, January 2011).",
            "Lung controls the docks; ABB territory expansion is escalating.",
            "Brockton Bay's gangs (ABB, Empire 88, Merchants) are at the pre-Endbringer status quo.",
            "The Wards (BB) are operating publicly; Shadow Stalker is on Wards probation.",
            "Coil is operating in Brockton Bay but unknown to civilians and most heroes.",
            "Endbringer cycle: Behemoth was the most recent attack; Leviathan is ~6 weeks out.",
        ],
        "public_knowledge": [
            "Cape gangs (ABB, E88, Merchants) and their territories.",
            "The Triumvirate (Legend, Alexandria, Eidolon) exists.",
            "Endbringers (Behemoth, Leviathan, Simurgh) are global existential threats.",
            "PRT classification system (Trump, Master, Stranger, Thinker, etc.).",
            "Local heroes (Armsmaster, Miss Militia, Dauntless, etc.).",
        ],
        "hidden_knowledge": [
            "Coil's identity / Thomas Calvert.",
            "Tattletale's existence (no debut yet).",
            "The Undersiders have not yet formed.",
            "Mannequin / Slaughterhouse 9 movements.",
            "Cauldron / Doctor Mother / Number Man.",
            "The Entities and the true nature of Shards.",
        ],
    },
    {
        "name": "Arc 2: Insinuation",
        "range": (2011, 4, 2011, 5),
        "canon_events": [
            "Taylor's first cape outing as Skitter; Lung confrontation in the docks.",
            "Lung is incapacitated by Skitter (and unbeknownst to her, Tattletale).",
            "The Undersiders (Grue, Tattletale, Bitch, Regent) approach Skitter.",
            "Bakuda is preparing her ABB takeover (not yet executed).",
        ],
        "public_knowledge": [
            "The Undersiders are a small new villain group operating in BB.",
            "Lung is missing or weakened; ABB power vacuum opening.",
        ],
        "hidden_knowledge": [
            "Coil's full operations and Calvert's PRT mole role.",
            "Bakuda's bombs and her pending ABB coup.",
            "Cauldron's involvement in shaping cape policy.",
        ],
    },
    {
        "name": "Arc 3-5: Agitation / Shell / Hive",
        "range": (2011, 5, 2011, 6),
        "canon_events": [
            "Bakuda triggers her ABB coup; bomb attacks across BB.",
            "Skitter's costume gets tinker upgrades (Parian collaboration).",
            "Bank robbery sets up Coil's plans for Dinah Alcott.",
            "Empire 88's expansion under Kaiser; Purity-Kaiser custody dispute.",
        ],
        "public_knowledge": [
            "Bakuda has gone rogue; ABB is in violent flux.",
            "Coil is a player in BB underworld (still anonymous).",
        ],
        "hidden_knowledge": [
            "Dinah Alcott's precognitive abilities.",
            "Coil's plan to acquire Dinah.",
            "Kaiser's Empire is about to fracture.",
        ],
    },
    {
        "name": "Arc 6-7: Tangle / Buzz",
        "range": (2011, 6, 2011, 7),
        "canon_events": [
            "Slaughterhouse Nine arrive in Brockton Bay; Jack Slash is selecting recruits.",
            "Empire 88 fractures; Kaiser is killed; Purity strikes out.",
            "Trickster, Sundancer, Genesis, Ballistic (Travelers) become more visible.",
            "Skitter rescues Dinah from Coil's basement (eventually).",
        ],
        "public_knowledge": [
            "S9 is in BB. Citywide panic.",
            "Empire collapse; vacuum filling with smaller gangs.",
        ],
        "hidden_knowledge": [
            "Jack Slash's full recruitment list.",
            "Cherish's family connection / Heartbreaker.",
        ],
    },
    {
        "name": "Arc 8: Extermination",
        "range": (2011, 7, 2011, 7),
        "canon_events": [
            "Leviathan attacks Brockton Bay (canonical, May/June 2011 in some readings).",
            "Major casualties: Aegis, Velocity, Dauntless, others.",
            "BB's cape demographics permanently reshaped; hero/villain alliances form against Levi.",
        ],
        "public_knowledge": [
            "Endbringer alarm: BB is the target.",
            "Triumvirate mobilising globally.",
        ],
        "hidden_knowledge": [
            "Levi-on-water dynamics; Eidolon's deliberate triggering of Endbringers.",
        ],
    },
    {
        "name": "Arc 11+: Infestation onward",
        "range": (2011, 8, 2012, 12),
        "canon_events": [
            "Skitter's reign over Brockton Bay's villain territory.",
            "Travelers' arc; Echidna manifestation; the Echidna fight.",
            "Skitter goes hero (Weaver) under PRT custody.",
            "Slaughterhouse 9000 attacks (Mannequin clones); Bonesaw subverts.",
            "Khonsu / Behemoth attack on Delhi / New Delhi.",
            "Gold Morning approaches as Scion turns hostile.",
        ],
        "public_knowledge": [
            "Increasingly chaotic global cape situation.",
            "Triumvirate strained; Cauldron's existence partially exposed.",
        ],
        "hidden_knowledge": [
            "Scion's true nature.",
            "Khepri arc events.",
        ],
    },
]


# ─── The Irregular at Magic High School (canonical: 2095 onward) ───────────────
#
# Mahouka volumes are hand-attested; date ranges are approximate.
_MAHOUKA_ARCS: list[dict] = [
    {
        "name": "Vol 1-2 (Enrollment I/II)",
        "range": (2095, 4, 2095, 5),
        "canon_events": [
            "First High School entrance ceremony; Bloom/Weed social hierarchy established.",
            "Tatsuya Shiba (Course 2) enters as the 'Irregular'; Miyuki (Course 1) is class rep.",
            "Hattori Hanzou's bias against Course 2 students surfaces.",
            "First major incident: Blanche extremists on First High campus.",
        ],
        "public_knowledge": [
            "Modern magic and the Ten Master Clans system.",
            "Strategic-Class magicians; international cape tensions.",
            "First High School and the Nine Schools.",
        ],
        "hidden_knowledge": [
            "Tatsuya's Yotsuba origins; his Decomposition / Regrowth abilities.",
            "Maya Yotsuba's identity as his aunt and clan head.",
            "Pixie's existence and the Parasite project.",
        ],
    },
    {
        "name": "Vol 3-4 (Nine Schools Competition I/II)",
        "range": (2095, 7, 2095, 8),
        "canon_events": [
            "Nine Schools Competition; First High vs other Schools.",
            "Tatsuya as the engineer's 'analytical' role; Mirage Bat events.",
            "Blanche's terrorist follow-up; magic-suppression devices appear.",
        ],
        "public_knowledge": [
            "Nine Schools tournament structure.",
            "International magic-tech competition pressures.",
        ],
        "hidden_knowledge": [
            "Cardinal George's intelligence operations against the Yotsuba.",
        ],
    },
    {
        "name": "Vol 5+ (Summer Holiday onward)",
        "range": (2095, 8, 2098, 0),
        "canon_events": [
            "Summer training camp; Morisaki–Lin field exercise.",
            "Yokohama Disturbance; Great Asian Alliance invasion.",
            "Master Clans Conference; Ancient City Insurrection; Yotsuba succession.",
            "Pursuit / Escape arcs leading into Sacrifice Graduation.",
        ],
        "public_knowledge": [
            "Public knowledge of Mahouka's geopolitical tensions.",
        ],
        "hidden_knowledge": [
            "True extent of Tatsuya's Material Burst capability.",
            "The Cardinal George conspiracy details.",
        ],
    },
]


CANON_ARCS: dict[str, list[dict]] = {
    "worm": _WORM_ARCS,
    "the irregular at magic high school": _MAHOUKA_ARCS,
    "mahouka koukou no rettousei": _MAHOUKA_ARCS,
    "mahouka": _MAHOUKA_ARCS,  # alias
}


# ─── Date parsing ────────────────────────────────────────────────────────────

_MONTH_RE = re.compile(
    r"\b(January|February|March|April|May|June|July|August|September|October|November|December|Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)\b",
    re.IGNORECASE,
)
_MONTH_MAP = {
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6,
    "july": 7, "august": 8, "september": 9, "october": 10, "november": 11, "december": 12,
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "sept": 9, "oct": 10, "nov": 11, "dec": 12,
}


def _parse_date(date_str: str) -> tuple[Optional[int], Optional[int]]:
    """Extract (year, month) from a free-form date string. Either may be None.

    Handles every shape we've seen in practice:
      "April 11, 2011"     -> (2011, 4)
      "2095-04-18 Evening" -> (2095, 4)
      "April 2095"         -> (2095, 4)
      "2011"               -> (2011, None)
    """
    if not date_str:
        return None, None
    year_match = re.search(r"\b(\d{4})\b", date_str)
    year = int(year_match.group(1)) if year_match else None
    month_match = _MONTH_RE.search(date_str)
    if month_match:
        month = _MONTH_MAP[month_match.group(1).lower()]
        return year, month
    # Try YYYY-MM- numeric form
    iso_match = re.search(r"\b(\d{4})-(\d{1,2})-?\b", date_str)
    if iso_match:
        return int(iso_match.group(1)), int(iso_match.group(2))
    return year, None


def _date_in_range(date_y: int, date_m: int | None, rng: ArcRange) -> bool:
    """Is the (year, month) within the arc's range? Inclusive on both ends.

    If the arc range has month=0 boundaries, treats them as wildcards
    (start_month=0 → from beginning of start_year; end_month=0 → through
    end of end_year).
    """
    s_y, s_m, e_y, e_m = rng
    if date_y < s_y or date_y > e_y:
        return False
    if date_y == s_y and s_m and date_m is not None and date_m < s_m:
        return False
    if date_y == e_y and e_m and date_m is not None and date_m > e_m:
        return False
    return True


def lookup_arc(universe: str, date_str: str) -> Optional[dict]:
    """Find the canonical arc for ``universe`` containing ``date_str``.

    Returns the arc dict with `name`, `canon_events`, `public_knowledge`,
    `hidden_knowledge`. None when no match (universe unknown, or date
    outside any arc range).
    """
    if not universe or not date_str:
        return None
    arcs = CANON_ARCS.get(universe.strip().lower())
    if not arcs:
        return None
    year, month = _parse_date(date_str)
    if year is None:
        return None
    # Try most-specific matches first (we walk in order; arcs list is
    # ordered by chronological start).
    for arc in arcs:
        if _date_in_range(year, month, arc["range"]):
            return arc
    return None


__all__ = ["CANON_ARCS", "lookup_arc"]
