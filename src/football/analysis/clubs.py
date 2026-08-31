"""Finding a club from what the user typed.

An exact slug is taken as given. Anything else is matched loosely against
both the slug and the display name, because "Albion" is three clubs and
"hove" is one — and guessing between them is exactly what a person is better
at than a rule.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass


@dataclass(frozen=True)
class Candidate:
    slug: str
    name: str


def find_clubs(clubs: Iterable[Candidate], query: str) -> list[Candidate]:
    """Clubs matching `query`, ordered by name.

    An exact slug match short-circuits: it is unambiguous by construction and
    must never be turned into a chooser.
    """
    clubs = list(clubs)
    text = (query or "").strip().lower()
    if not text:
        return []

    for club in clubs:
        if club.slug.lower() == text:
            return [club]

    matched = [club for club in clubs
               if text in club.slug.lower() or text in club.name.lower()]
    return sorted(matched, key=lambda club: club.name)
