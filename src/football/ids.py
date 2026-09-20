"""Slugs and deterministic identifiers.

`match_id` depends only on the date and the two clubs, so the same match
derived from either club's fixture list produces the same identifier — which
is how the store guarantees a match is never recorded twice.
"""

import re
import unicodedata
from datetime import date as _date

_NON_SLUG = re.compile(r"[^a-z0-9]+")
#: Apostrophes join a word rather than break it: "Nott'm" is one word, so it
#: must slug as "nottm", not "nott-m".
_APOSTROPHE = re.compile(r"['\u2019]")
#: "&" is punctuation and disappears into _NON_SLUG, but a literal "and"
#: survives as a word \u2014 so "Brighton & Hove Albion" and "Brighton and Hove
#: Albion" would otherwise slug differently despite naming the same club.
#: Folding the word onto "&" first makes both collapse to one slug.
_AND = re.compile(r"\band\b")


def slugify(name: str) -> str:
    """Reduce a display name to a lowercase hyphenated slug."""
    decomposed = unicodedata.normalize("NFKD", name)
    ascii_only = decomposed.encode("ascii", "ignore").decode("ascii")
    without_and = _AND.sub("&", ascii_only.lower())
    without_apostrophes = _APOSTROPHE.sub("", without_and)
    slug = _NON_SLUG.sub("-", without_apostrophes).strip("-")
    if not slug:
        raise ValueError(f"name {name!r} produces an empty slug")
    return slug


def match_id(date: str, home_slug: str, away_slug: str) -> str:
    """Build the deterministic identifier for a match."""
    try:
        _date.fromisoformat(date)
    except ValueError as exc:
        raise ValueError(f"date {date!r} is not ISO YYYY-MM-DD") from exc
    return f"{date}_{home_slug}_{away_slug}"
