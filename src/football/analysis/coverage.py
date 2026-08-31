"""Where the record is known to be missing matches.

Every other module asks what the matches say. This one asks which matches
are absent — not the ones with a blank score, which the record admits to,
but the ones it does not know it lacks.

The record can spot two kinds of gap in itself.

A season held **in part**: a club that played FA Cup ties that season was,
that season, in a league; if we hold the ties and no league match at all, a
league programme is missing. Brighton's record holds ten such seasons before
1920-21 and 1945-46, when the club played Southern League and wartime
regional football that nobody has imported.

A season held **not at all**: a season between the club's first and last
with no match of any kind. Barrow's record leaps from 1971-72 to 2016-17
because their non-League decades are in no source we hold. Nothing in those
seasons gives the gap away — there are no cup ties to notice — so it is
found by looking for the seasons that are missing rather than at the
matches that are there.

That matters wherever adjacency does. Two matches next to each other in the
record are not necessarily two matches next to each other in life, and a
sequence that assumes they are states as fact something the record cannot
know — the same objection as counting an unrecorded score as nil.

The war years count as gaps. The record holds nothing for 1915-16 to
1919-20 or 1939-40 to 1944-45, and these clubs played regional football
throughout both. Whether a run survives a war is a question the record
cannot answer, and the whole point here is not to answer it silently.

What this cannot see: a season imported in part. A missing half-programme
breaks no rule here and looks exactly like a complete one.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterable

#: Seasons in which the club appears with no league match at all. A cup tie
#: is proof the club was playing that season; no league match beside it is
#: proof we are missing the league programme.
_INCOMPLETE = """
SELECT cm.season
FROM club_matches cm
LEFT JOIN competitions comp ON comp.slug = cm.competition
WHERE cm.club = ?
GROUP BY cm.season
HAVING COALESCE(SUM(CASE WHEN comp.type = 'league' THEN 1 ELSE 0 END), 0) = 0
"""


def incomplete_seasons(conn: sqlite3.Connection, club: str,
                       competition: str | None = None) -> frozenset[str]:
    """Seasons where this club's record is known to be missing matches.

    A question about a single competition is judged against that
    competition: "the longest run of FA Cup ties without a goal" is a fair
    question of a record holding every FA Cup tie, whatever else is absent.
    Only an answer drawn from several competitions can be undone by one of
    them being missing.
    """
    if competition:
        return frozenset()
    return frozenset(season for (season,) in conn.execute(_INCOMPLETE, (club,)))


#: Every season the club appears in, oldest first.
_PRESENT = """
SELECT DISTINCT cm.season FROM club_matches cm WHERE cm.club = ?
ORDER BY cm.season
"""


def absent_seasons(conn: sqlite3.Connection, club: str) -> frozenset[str]:
    """Seasons inside the club's record that hold no match at all.

    Unlike a season held in part, this is judged whatever competition is
    being asked about: a season the record skips entirely is missing that
    competition too, whether or not the club would have had a match in it.
    """
    present = [season for (season,) in conn.execute(_PRESENT, (club,))]
    if not present:
        return frozenset()
    years = range(int(present[0][:4]), int(present[-1][:4]) + 1)
    return frozenset(season for season in map(_season, years)
                     if season not in set(present))


def _season(year: int) -> str:
    """The season starting in `year`, written as the record writes it."""
    return f"{year}-{(year + 1) % 100:02d}"


def divides(first: str, second: str, absent: frozenset[str]) -> bool:
    """Whether a gap in the record lies between these two seasons."""
    return any(first < season < second for season in absent)


def spans(seasons: Iterable[str]) -> list[tuple[str, str]]:
    """Consecutive seasons gathered into (first, last) ranges."""
    ordered = sorted(seasons)
    if not ordered:
        return []

    found, first, last = [], ordered[0], ordered[0]
    for season in ordered[1:]:
        if int(season[:4]) == int(last[:4]) + 1:
            last = season
            continue
        found.append((first, last))
        first = last = season
    found.append((first, last))
    return found


def stretches(seasons: Iterable[str]) -> list[str]:
    """Those ranges written out, for reporting.

    Eleven seasons listed one by one is a wall; "1905-06 to 1914-15,
    1945-46" is the same fact read at a glance.
    """
    return [first if first == last else f"{first} to {last}"
            for first, last in spans(seasons)]
