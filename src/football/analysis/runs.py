"""Longest sequences: unbeaten, wins, losses, clean sheets.

Uses `final_result`, not `result`: a cup tie lost on penalties ends an
unbeaten run in every sense a supporter would recognise, even though the
90-minute record calls it a draw.

Computed in Python rather than with window functions. The dataset is small,
and the awkward part is not the arithmetic but deciding what breaks a run —
which is far easier to read, and to test, as a loop.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from football.analysis.filters import Filters, select

#: What each run type counts as continuing it.
_CONTINUES = {
    "unbeaten": lambda row: row.result in ("W", "D"),
    "wins": lambda row: row.result == "W",
    "losses": lambda row: row.result == "L",
    "draws": lambda row: row.result == "D",
    "without-win": lambda row: row.result in ("D", "L"),
    "clean-sheets": lambda row: row.goals_against == 0,
}


@dataclass(frozen=True)
class Match:
    date: str
    season: str
    competition: str
    opponent: str
    home_or_away: str
    goals_for: int | None
    goals_against: int | None
    result: str | None


@dataclass(frozen=True)
class Run:
    length: int
    start: Match
    end: Match

    def describe(self) -> str:
        return (f"{self.length} matches, {self.start.date} to {self.end.date} "
                f"({self.start.season} to {self.end.season})")


def matches_in_order(conn: sqlite3.Connection, filters: Filters) -> list[Match]:
    """Every match under these filters, oldest first."""
    sql, params = select(
        """
        cm.date, cm.season, cm.competition, cm.opponent, cm.home_or_away,
        cm.goals_for, cm.goals_against, cm.final_result
        """,
        filters,
        order="cm.date, cm.match_id",
    )
    return [Match(*row) for row in conn.execute(sql, params).fetchall()]


def longest(matches: list[Match], of: str) -> Run | None:
    """The longest run of `of`. Returns None if there is never one.

    A match with no recorded result breaks the run rather than extending it:
    an unbeaten sequence through a match nobody knows the outcome of is not a
    fact, it is an assumption.
    """
    continues = _CONTINUES[of]
    best: Run | None = None
    current: list[Match] = []

    for match in matches:
        known = match.result is not None and (
            of != "clean-sheets" or match.goals_against is not None)
        if known and continues(match):
            current.append(match)
            if best is None or len(current) > best.length:
                best = Run(length=len(current), start=current[0], end=current[-1])
        else:
            current = []

    return best


def all_runs(matches: list[Match], of: str, minimum: int = 2) -> list[Run]:
    """Every run of at least `minimum`, longest first."""
    continues = _CONTINUES[of]
    runs: list[Run] = []
    current: list[Match] = []

    def close() -> None:
        if len(current) >= minimum:
            runs.append(Run(length=len(current), start=current[0], end=current[-1]))

    for match in matches:
        known = match.result is not None and (
            of != "clean-sheets" or match.goals_against is not None)
        if known and continues(match):
            current.append(match)
        else:
            close()
            current.clear()
    close()

    return sorted(runs, key=lambda run: (-run.length, run.start.date))
