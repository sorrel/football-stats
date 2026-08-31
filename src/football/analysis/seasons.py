"""Derive what a league season led to, and how far a cup run went.

Neither is stored. Promotion and relegation are not published as data, and
encoding the rules per era would be a large table that changed repeatedly
(play-offs from 1987, re-election before then, varying numbers up and down)
and could be wrong in ways the results could not contradict.

Instead the outcome falls out of two facts already held: the tier the club
played at the following season, and whether they played any play-off matches.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

OUTCOMES = ("promoted", "promoted-via-play-offs", "play-offs-lost",
            "relegated", "stayed", "war", "left-the-league", "current")

#: The seasons English league football was suspended. A gap spanning either
#: is wartime; any other gap is a club that left the League — Accrington
#: Stanley resigned in 1962, Barrow and Workington were voted out — and must
#: not be labelled war.
_WARS = ((1915, 1919), (1939, 1946))


@dataclass(frozen=True)
class LeagueSeason:
    season: str
    competition: str
    tier: int | None
    position: int | None
    points: int | None
    point_adjustment: int | None
    played_play_offs: bool = False


def _follows(earlier: str, later: str) -> bool:
    """True if `later` is the season immediately after `earlier`.

    A gap — wartime, or simply a season we do not hold — must not imply an
    outcome, so consecutiveness is checked rather than assumed from ordering.
    """
    try:
        return int(later[:4]) == int(earlier[:4]) + 1
    except (ValueError, IndexError):
        return False


def _gap_reason(earlier: str, later: str) -> str:
    """Why two league seasons are not consecutive.

    Every gap has a reason, and saying which is more use than "unknown".
    """
    try:
        start, resume = int(earlier[:4]) + 1, int(later[:4])
    except (ValueError, IndexError):
        return "left-the-league"
    for war_start, war_end in _WARS:
        if start <= war_end and resume >= war_start:
            return "war"
    return "left-the-league"


def outcome(seasons: list[LeagueSeason], index: int) -> str:
    """What the season at `index` led to. `seasons` must be in date order."""
    this = seasons[index]
    following = seasons[index + 1] if index + 1 < len(seasons) else None

    if following is None:
        return "current"
    if this.tier is None or following.tier is None:
        return "left-the-league"
    if not _follows(this.season, following.season):
        return _gap_reason(this.season, following.season)

    if following.tier > this.tier:
        return "relegated"
    if following.tier < this.tier:
        return "promoted-via-play-offs" if this.played_play_offs else "promoted"
    return "play-offs-lost" if this.played_play_offs else "stayed"


def _int(value) -> int | None:
    return None if value is None else int(value)


def league_seasons(conn: sqlite3.Connection, club: str) -> list[LeagueSeason]:
    """Every league season the club played, oldest first.

    Built from the matches, so a season with no stored table still appears —
    the matches are the record of what was played. Play-off matches are
    counted only as a flag on the league season they belong to.
    """
    rows = conn.execute(
        """
        SELECT cm.season,
               MAX(CASE WHEN c.type = 'league' THEN cm.competition END),
               MAX(CASE WHEN c.type = 'league' THEN m.tier END),
               MAX(c.type = 'play-off')
        FROM club_matches cm
        JOIN matches m ON m.match_id = cm.match_id
        JOIN competitions c ON c.slug = cm.competition
        WHERE cm.club = ? AND c.type IN ('league', 'play-off')
        GROUP BY cm.season
        ORDER BY cm.season
        """,
        (club,),
    ).fetchall()

    stored = {
        row[0]: row
        for row in conn.execute(
            "SELECT season, position, points, point_adjustment "
            "FROM seasons WHERE club = ?", (club,)).fetchall()
    }

    seasons = []
    for season, competition, tier, play_offs in rows:
        if competition is None:
            continue  # play-off matches with no league season alongside them
        table = stored.get(season)
        seasons.append(LeagueSeason(
            season=season, competition=competition, tier=_int(tier),
            position=_int(table[1]) if table else None,
            points=_int(table[2]) if table else None,
            point_adjustment=_int(table[3]) if table else None,
            played_play_offs=bool(play_offs),
        ))
    return seasons


def season_rows(conn: sqlite3.Connection, club: str
                ) -> list[tuple[LeagueSeason, str]]:
    """Every league season with its derived outcome."""
    seasons = league_seasons(conn, club)
    return [(season, outcome(seasons, index))
            for index, season in enumerate(seasons)]


#: How far through a competition each round is. Sources name the same round
#: differently — the FA Cup fifth round is the round of 16, and the sixth
#: round is the quarter-final — so synonyms share a rank rather than being
#: ordered as though they were separate stages.
_ROUND_RANKS = {
    "Preliminary Round": 0,
    "Qualifying Round": 1,
    "Round 1": 2,
    "Round 2": 3,
    "Round 3": 4,
    "Round 4": 5,
    "Round 5": 6,
    # Europe names this stage rather than numbering it; the domestic cups'
    # spellings are normalised on import, so only Europe reaches here.
    "Round of 16": 6,
    "Round 6": 7,
    "Quarter-final": 7,
    "Semi-final": 8,
    "Final": 9,
}

#: Group stages sit before any knockout round.
_GROUP_RANK = 1


def _round_rank(name: str) -> int:
    if name in _ROUND_RANKS:
        return _ROUND_RANKS[name]
    return _GROUP_RANK if name.startswith("Group") else -1


def cup_runs(conn: sqlite3.Connection, club: str) -> list[tuple[str, str, str, str]]:
    """How far each cup run went: (season, competition, round, result).

    The result uses the final outcome, so a tie lost on penalties ends the
    run — as it did in fact.
    """
    rows = conn.execute(
        """
        SELECT cm.season, cm.competition, cm.round, cm.final_result, cm.date
        FROM club_matches cm
        JOIN competitions c ON c.slug = cm.competition
        WHERE cm.club = ? AND c.type NOT IN ('league', 'play-off')
        ORDER BY cm.season, cm.competition, cm.date
        """,
        (club,),
    ).fetchall()

    furthest: dict[tuple[str, str], tuple[int, str, str]] = {}
    for season, competition, round_name, result, _ in rows:
        key = (season, competition)
        rank = _round_rank(round_name or "")
        if key not in furthest or rank >= furthest[key][0]:
            furthest[key] = (rank, round_name or "", result or "")

    out = []
    for (season, competition), (_, round_name, result) in sorted(furthest.items()):
        if round_name == "Final":
            ending = "Winners" if result == "W" else "Runners-up"
        else:
            ending = round_name
        out.append((season, competition, round_name, ending))
    return out
