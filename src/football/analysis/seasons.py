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
WARS = ((1915, 1919), (1939, 1946))


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
    for war_start, war_end in WARS:
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


#: The round an early exit needs to reach before it stops being poor —
#: tougher for a club playing Championship football or above, since more is
#: expected of them than of one in League One or Two.
_EARLY_EXIT_THRESHOLD = {"upper": _round_rank("Round 3"), "lower": _round_rank("Round 1")}


def _cup_category(round_name: str, ending: str, tier: int | None) -> str:
    """How a cup run reads: one of the best four rounds, a poor exit for the
    level the club played at that season, or neither.

    A tier we do not hold for that season says nothing about what was
    expected, so it is judged on neither: a merely unknown level must not
    read as a low one.
    """
    if ending == "Winners":
        return "winners"
    if round_name == "Final":
        return "final"
    if round_name in ("Semi-final", "Quarter-final"):
        return round_name.lower()
    if tier is not None:
        threshold = (_EARLY_EXIT_THRESHOLD["upper"] if tier <= 2
                     else _EARLY_EXIT_THRESHOLD["lower"])
        if _round_rank(round_name) <= threshold:
            return "early-exit"
    return ""


def _ending(round_name: str, result: str) -> str:
    """How a furthest round reads: what happened there, not just its name.

    A final's name alone is silent on whether it was won, and a group
    stage's own letter or number is a detail nobody asked this for — a
    supporter compares a season's group form to another season's, not
    Group C to Group F.
    """
    if round_name == "Final":
        return "Winners" if result == "W" else "Runners-up"
    if round_name.startswith("Group"):
        return "Group Stage"
    return round_name


def cup_runs(conn: sqlite3.Connection, club: str
            ) -> list[tuple[str, str, str, str, str]]:
    """How far each cup run went: (season, competition, round, result, category).

    One row per competition the club entered that season, and — only when
    there was more than one, so a lone entry is not repeated as its own
    total — a `"Combined"` row for the furthest any of them reached: a
    supporter's sense of "how did the cups go that year" is not tied to any
    one of them.

    The result uses the final outcome, so a tie lost on penalties ends the
    run — as it did in fact. `category` is `_cup_category`'s judgement of
    the run, using the tier the club played at in the league that season.
    """
    rows = conn.execute(
        """
        SELECT cm.season, cm.competition, c.name, cm.round, cm.final_result, cm.date
        FROM club_matches cm
        JOIN competitions c ON c.slug = cm.competition
        WHERE cm.club = ? AND c.type NOT IN ('league', 'play-off')
        ORDER BY cm.season, cm.competition, cm.date
        """,
        (club,),
    ).fetchall()

    furthest: dict[tuple[str, str], tuple[int, str, str, str]] = {}
    for season, competition, name, round_name, result, _ in rows:
        key = (season, competition)
        rank = _round_rank(round_name or "")
        if key not in furthest or rank >= furthest[key][0]:
            furthest[key] = (rank, round_name or "", result or "", name or competition)

    tiers = {season.season: season.tier for season in league_seasons(conn, club)}

    def _row(season: str, label: str, round_name: str, result: str) -> tuple:
        ending = _ending(round_name, result)
        return (season, label, round_name, ending,
                _cup_category(round_name, ending, tiers.get(season)))

    by_season: dict[str, list[tuple[str, int, str, str, str]]] = {}
    for (season, _competition), (rank, round_name, result, name) in furthest.items():
        by_season.setdefault(season, []).append((name, rank, round_name, result))

    out = []
    for season, entries in sorted(by_season.items()):
        for name, _rank, round_name, result in sorted(entries):
            out.append(_row(season, name, round_name, result))
        if len(entries) > 1:
            _, rank, round_name, result = max(entries, key=lambda entry: entry[1])
            out.append(_row(season, "Combined", round_name, result))
    return out
