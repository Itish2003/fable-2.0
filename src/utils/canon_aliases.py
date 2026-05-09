"""Canonical character + alias dictionary for Mahouka and Jujutsu Kaisen.

Used by:
  - scripts/backfill_canon_chunk_entities.py (Phase B): resolve mentions
    in raw canon chunks to canonical entity nodes.
  - src/nodes/archivist_merge.py commit_lore (Phase C): canonicalise
    incoming entity names so future runs don't recreate "Miyuki Shiba"
    + "Shiba Miyuki" + "Onii-sama" as three separate lore_nodes.

Design choices:

1. **Canonical name = "Given Surname"** (Western fan-translation
   convention). The corpus uses both orders interchangeably; we pick
   one and normalise everything to it.

2. **Aliases include all attested forms**: name-order swap,
   single-name (given-only or surname-only when unambiguous),
   honorifics, codenames, titles. Empty alias list means "exact
   canonical match required."

3. **Ambiguous bare names are EXCLUDED from aliases**. "Shiba" alone
   could be Tatsuya OR Miyuki -- without a given-name disambiguator
   we don't link. The :data:`AMBIGUOUS_BARE_NAMES` set documents
   these explicitly.

4. **Given names are unambiguous in practice for our cast.** "Tatsuya",
   "Miyuki", "Erika" each refer to exactly one person. So given-only
   mentions resolve cleanly.

This list covers the recurring cast (~30-40 per universe) NOT every
named entity. One-off characters who don't appear across multiple
volumes are intentionally omitted -- they wouldn't survive the
chunk-frequency threshold anyway.
"""

from __future__ import annotations

import re
from typing import Optional


# ─── Mahouka Koukou no Rettousei ────────────────────────────────────────────
_MAHOUKA: dict[str, list[str]] = {
    # First High School - Class 1-E (Course 2 / "Weeds") - protagonist's circle
    "Tatsuya Shiba": ["Shiba Tatsuya", "Tatsuya", "Onii-sama", "Onii-san"],
    "Miyuki Shiba": ["Shiba Miyuki", "Miyuki"],
    "Erika Chiba": ["Chiba Erika", "Erika"],
    "Mizuki Shibata": ["Shibata Mizuki", "Mizuki"],
    "Leonhart Saijou": ["Saijou Leonhart", "Leo", "Leonhart", "Leon"],
    "Mikihiko Yoshida": ["Yoshida Mikihiko", "Mikihiko"],
    "Honoka Mitsui": ["Mitsui Honoka", "Honoka"],
    "Shizuku Kitayama": ["Kitayama Shizuku", "Shizuku"],
    "Subaru Satomi": ["Satomi Subaru", "Subaru"],

    # First High School - Class 1-A (Course 1 / "Blooms")
    "Shun Morisaki": ["Morisaki Shun", "Morisaki"],

    # First High School - Student Council & Disciplinary Committee
    "Mayumi Saegusa": ["Saegusa Mayumi", "Mayumi", "President Saegusa"],
    "Mari Watanabe": ["Watanabe Mari", "Mari"],
    "Suzune Ichihara": ["Ichihara Suzune", "Suzune", "Rin-chan"],
    "Azusa Nakajou": ["Nakajou Azusa", "Azusa", "A-chan"],
    "Hanzou Hattori": ["Hattori Hanzou", "Hattori", "Hattori Gyoubushou"],
    "Katsuto Juumonji": ["Juumonji Katsuto", "Juumonji"],
    "Isori Kei": ["Kei Isori", "Isori"],
    "Kanon Chiyoda": ["Chiyoda Kanon", "Kanon"],

    # Tatsuya/Miyuki extended family (Yotsuba clan)
    "Maya Yotsuba": ["Yotsuba Maya", "Maya"],
    "Hayama Tadanori": ["Tadanori Hayama", "Hayama"],
    "Minami Sakurai": ["Sakurai Minami"],
    "Honami Sakurai": ["Sakurai Honami", "Honami"],
    "Miya Shiba": ["Shiba Miya", "Miya"],
    "Tatsurou Shiba": ["Shiba Tatsurou", "Tatsurou"],

    # Military / Independent Magic Battalion
    "Harunobu Kazama": ["Kazama Harunobu", "Kazama", "Major Kazama", "Colonel Kazama"],
    "Kyouko Fujibayashi": ["Fujibayashi Kyouko", "Fujibayashi"],
    "Sanada Shigeru": ["Shigeru Sanada", "Sanada"],
    "Yanagi Muraji": ["Muraji Yanagi", "Yanagi"],

    # Antagonists / international cast
    "Angelina Kudou Shields": ["Kudou Shields Angelina", "Lina", "Angie Sirius", "Sirius"],
    "Minoru Kudou": ["Kudou Minoru"],
    "Pixie": ["3H", "3H-CAD"],

    # Mayumi Saegusa's sisters
    "Kasumi Saegusa": ["Saegusa Kasumi", "Kasumi"],
    "Izumi Saegusa": ["Saegusa Izumi", "Izumi"],

    # Other recurring
    "Lu Ganghu": ["Ganghu Lu"],
    "Zhang Renhao": ["Renhao Zhang"],
}

# ─── Jujutsu Kaisen ─────────────────────────────────────────────────────────
_JUJUTSU: dict[str, list[str]] = {
    # Tokyo Jujutsu High - 1st years
    "Yuji Itadori": ["Itadori Yuji", "Yuji", "Itadori"],
    "Megumi Fushiguro": ["Fushiguro Megumi", "Megumi"],
    "Nobara Kugisaki": ["Kugisaki Nobara", "Nobara", "Kugisaki"],

    # Tokyo Jujutsu High - 2nd years
    "Maki Zenin": ["Zenin Maki", "Maki"],
    "Toge Inumaki": ["Inumaki Toge", "Toge", "Inumaki"],
    "Panda": [],

    # Tokyo Jujutsu High - 3rd years / past
    "Yuta Okkotsu": ["Okkotsu Yuta", "Yuta", "Okkotsu"],
    "Kasumi Miwa": ["Miwa Kasumi"],

    # Faculty / Mentors
    "Satoru Gojo": ["Gojo Satoru", "Gojo", "Satoru"],
    "Masamichi Yaga": ["Yaga Masamichi", "Principal Yaga", "Yaga"],
    "Kiyotaka Ijichi": ["Ijichi Kiyotaka", "Ijichi"],
    "Shoko Ieiri": ["Ieiri Shoko", "Shoko", "Ieiri"],
    "Kento Nanami": ["Nanami Kento", "Nanami"],
    "Mei Mei": [],
    "Utahime Iori": ["Iori Utahime", "Utahime"],
    "Aoi Todo": ["Todo Aoi", "Todo"],

    # Antagonists
    "Suguru Geto": ["Geto Suguru", "Geto"],
    "Sukuna": ["Ryomen Sukuna", "Ryoumen Sukuna"],
    "Mahito": [],
    "Jogo": [],
    "Hanami": [],
    "Dagon": [],
    "Choso": [],
    "Toji Fushiguro": ["Fushiguro Toji", "Toji", "Toji Zenin"],
    "Kenjaku": [],
    "Yuki Tsukumo": ["Tsukumo Yuki"],

    # Other notable
    "Naobito Zenin": ["Zenin Naobito", "Naobito"],
    "Naoya Zenin": ["Zenin Naoya", "Naoya"],
}


# ─── Worm by Wildbow ────────────────────────────────────────────────────────
#
# Worm is a 1.7M-word web serial. Most characters have a CIVILIAN NAME and a
# CAPE NAME. The cape name is canonical for retrieval (it's how they're
# referred to in scenes most of the time); civilian names are aliases.
#
# Naming convention: "<Cape Name>" is canonical. "<Civilian Name>" is an
# alias. For unmasked / civilian-only characters (Danny, Sophia's family,
# etc.) use the civilian name canonical.
#
_WORM: dict[str, list[str]] = {
    # Undersiders (Taylor's team)
    "Skitter": ["Taylor Hebert", "Taylor", "Hebert", "Weaver", "Khepri"],
    "Tattletale": ["Lisa Wilbourn", "Lisa", "Sarah Livsey"],
    "Bitch": ["Rachel Lindt", "Rachel", "Hellhound"],
    "Grue": ["Brian Laborn", "Brian"],
    "Regent": ["Alec", "Hijack"],
    "Imp": ["Aisha Laborn", "Aisha"],
    "Parian": ["Sabah"],
    "Foil": ["Flechette", "Lily"],

    # Wards (Brockton Bay protectorate juniors)
    "Clockblocker": ["Dennis"],
    "Vista": ["Missy Biron", "Missy"],
    "Aegis": ["Carlos"],
    "Gallant": ["Dean Stansfield", "Dean"],
    "Kid Win": ["Chris"],
    "Browbeat": [],
    "Shadow Stalker": ["Sophia Hess", "Sophia"],
    "Triumph": ["Rory Christner", "Rory"],
    "Flechette": ["Foil", "Lily"],

    # Brockton Bay Protectorate (adults)
    "Armsmaster": ["Colin Wallis", "Colin", "Defiant"],
    "Miss Militia": ["Hannah"],
    "Dauntless": [],
    "Battery": ["Puppy", "Battery"],
    "Assault": ["Madcap", "Ethan"],
    "Velocity": [],

    # Triumvirate (national heroes)
    "Legend": ["Keith"],
    "Alexandria": ["Rebecca Costa-Brown", "Rebecca"],
    "Eidolon": ["David"],

    # Cauldron / conspiracy
    "Contessa": ["Fortuna"],
    "Doctor Mother": [],
    "Number Man": ["Kurt", "Harbinger"],

    # Slaughterhouse Nine
    "Jack Slash": ["Jack", "Jacob"],
    "Bonesaw": ["Riley Davis", "Riley"],
    "Crawler": ["Ned"],
    "Mannequin": ["Alan Gramme", "Alan"],
    "Burnscar": ["Mimi"],
    "Cherish": ["Cherie Vasil", "Cherie"],
    "Shatterbird": [],
    "Siberian": ["Manton", "William Manton"],
    "Hatchet Face": [],
    "Hookwolf": ["Brad Meadows", "Brad"],

    # Empire 88 / villains
    "Kaiser": ["Max Anders", "Max"],
    "Purity": ["Kayden Anders", "Kayden"],
    "Krieg": [],
    "Othala": [],
    "Victor": [],
    "Stormtiger": [],
    "Cricket": [],
    "Night": [],
    "Fog": [],
    "Rune": [],
    "Crusader": [],

    # ABB
    "Lung": ["Kenta"],
    "Oni Lee": [],
    "Bakuda": [],

    # Other recurring villains / capes
    "Coil": ["Thomas Calvert", "Calvert"],
    "Echidna": ["Noelle Meinhardt", "Noelle"],
    "Trickster": ["Krouse"],
    "Sundancer": ["Marissa Newland", "Marissa"],
    "Genesis": [],
    "Ballistic": [],
    "Faultline": ["Melanie Fitch", "Melanie"],
    "Newter": [],
    "Spitfire": [],
    "Gregor the Snail": ["Gregor"],
    "Labyrinth": ["Elle"],
    "Mouse Protector": [],
    "Dragon": [],
    "Tagg": [],
    "Glaistig Uaine": ["Faerie Queen", "Ciara"],

    # Endbringers
    "Leviathan": [],
    "Behemoth": [],
    "Simurgh": ["Ziz"],

    # Civilians + supporting
    "Danny Hebert": ["Daniel Hebert"],
    "Annette Hebert": [],
    "Emma Barnes": ["Emma"],
    "Madison Clements": ["Madison"],
    "Greg Veder": ["Greg"],
    "Mr. Gladly": ["Mr Gladly", "Mr. G"],
    "Charlotte": [],
    "Forrest": [],
    "Sierra": [],
    "Bryce Kiley": ["Bryce"],

    # Birdcage / late-game
    "Marquis": ["Amelia's father"],
    "Panacea": ["Amy Dallon", "Amy"],
    "Glory Girl": ["Victoria Dallon", "Victoria", "Antares"],
    "Carol Dallon": ["Brandish"],
    "Mark Dallon": ["Flashbang"],
    "Crystal Pelham": ["Laserdream"],
    "Eric Pelham": ["Shielder"],
    "Sarah Pelham": ["Lady Photon"],
    "Neil Pelham": ["Manpower"],

    # Misc / late
    "Scion": ["Zion", "Warrior"],
    "Tohu": [],
    "Bohu": [],
    "Saint": [],
    "Teacher": [],
}


# ─── Reverse index + helpers ────────────────────────────────────────────────

CANON_CHARACTERS: dict[str, list[str]] = {**_MAHOUKA, **_JUJUTSU, **_WORM}

# Bare surnames that appear in multiple canonical names. NEVER resolve these
# alone; require a given-name disambiguator. Maintained manually because the
# detection logic needs to be conservative (false positives are worse than
# false negatives for entity linking).
AMBIGUOUS_BARE_NAMES: set[str] = {
    # Mahouka surnames shared across multiple canonical characters
    "Shiba",       # Tatsuya, Miyuki, Miya, Tatsurou
    "Saegusa",     # Mayumi, Kasumi, Izumi
    "Yotsuba",     # Maya (also a clan name)
    "Fushiguro",   # Megumi, Toji
    "Sakurai",     # Minami, Honami
    "Kudou",       # Angelina, Minoru
    "Zenin",       # Maki, Toji, Naobito, Naoya
    "Chiba",       # Erika (and "Chiba prefecture")
    "Yoshida",     # Mikihiko (common surname)
    "Mitsui",      # Honoka (common surname)
    "Iori",        # Utahime / Isori

    # Worm: shared surnames within the canonical cast
    "Hebert",      # Taylor + Danny + Annette
    "Anders",      # Max Kaiser + Kayden Purity
    "Pelham",      # Sarah + Neil + Crystal + Eric (New Wave)
    "Dallon",      # Carol + Mark + Amy + Victoria
    "Laborn",      # Brian + Aisha
    "Manton",      # William + Siberian
}


def _build_alias_index() -> dict[str, str]:
    """Reverse index: alias_lower -> canonical_name.

    Built once at module import. Includes:
      - The canonical name itself (lowercased)
      - Every alias from the dict (lowercased)
    Excludes single-word entries that are in AMBIGUOUS_BARE_NAMES.
    """
    idx: dict[str, str] = {}
    for canonical, aliases in CANON_CHARACTERS.items():
        idx[canonical.lower()] = canonical
        for a in aliases:
            a_lower = a.lower()
            # Drop single-word ambiguous surnames from the index
            if " " not in a and a in AMBIGUOUS_BARE_NAMES:
                continue
            idx[a_lower] = canonical
    return idx


_ALIAS_INDEX = _build_alias_index()


def resolve_alias(name: str) -> Optional[str]:
    """Resolve a name string (any case, any whitespace) to its canonical
    "Given Surname" form. Returns None if the name doesn't match any
    known canonical character or alias.
    """
    if not name:
        return None
    key = " ".join(name.split()).lower()  # collapse whitespace + lowercase
    return _ALIAS_INDEX.get(key)


# Compile a single regex that matches any alias as a whole word. Sorted by
# length descending so multi-word aliases match before single-word fragments
# (e.g. "Tatsuya Shiba" must be tried before "Tatsuya" alone).
def _build_mention_regex() -> re.Pattern:
    all_aliases: list[str] = []
    for canonical, aliases in CANON_CHARACTERS.items():
        all_aliases.append(canonical)
        for a in aliases:
            if " " not in a and a in AMBIGUOUS_BARE_NAMES:
                continue
            all_aliases.append(a)
    # Longest-first so "Tatsuya Shiba" matches before "Tatsuya"
    all_aliases.sort(key=len, reverse=True)
    pattern = "|".join(re.escape(a) for a in all_aliases)
    return re.compile(rf"\b({pattern})\b", flags=re.IGNORECASE)


_MENTION_RE = _build_mention_regex()


def find_mentions(text: str) -> dict[str, int]:
    """Scan ``text`` for canon-character mentions. Returns
    ``{canonical_name: mention_count}``.

    Multi-word aliases are matched before single-word ones (longest-first)
    so "Tatsuya Shiba" counts as one mention, not as Tatsuya + Shiba.

    Empty dict when no canon character is detected. The chunk's primary
    entity is the highest-count entry; ties broken by first-appearance.
    """
    if not text:
        return {}
    counts: dict[str, int] = {}
    first_pos: dict[str, int] = {}
    for m in _MENTION_RE.finditer(text):
        matched = m.group(0)
        canonical = resolve_alias(matched)
        if canonical is None:
            continue
        counts[canonical] = counts.get(canonical, 0) + 1
        first_pos.setdefault(canonical, m.start())
    return counts


def primary_entity(text: str) -> Optional[str]:
    """Return the canonical name with the most mentions in ``text``. Ties
    broken by earliest first-appearance position.
    """
    if not text:
        return None
    counts: dict[str, int] = {}
    first_pos: dict[str, int] = {}
    for m in _MENTION_RE.finditer(text):
        matched = m.group(0)
        canonical = resolve_alias(matched)
        if canonical is None:
            continue
        counts[canonical] = counts.get(canonical, 0) + 1
        first_pos.setdefault(canonical, m.start())
    if not counts:
        return None
    # max by (count, -first_pos) => most mentions, then earliest
    return max(counts.items(), key=lambda kv: (kv[1], -first_pos[kv[0]]))[0]


__all__ = [
    "CANON_CHARACTERS",
    "AMBIGUOUS_BARE_NAMES",
    "resolve_alias",
    "find_mentions",
    "primary_entity",
]
