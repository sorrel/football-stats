"""Longest sequences: unbeaten, wins, losses, clean sheets, goalless.

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
from datetime import date

from football.analysis.filters import Filters, select

#: What each run type counts as continuing it.
_CONTINUES = {
    "unbeaten": lambda row: row.result in ("W", "D"),
    "wins": lambda row: row.result == "W",
    "losses": lambda row: row.result == "L",
    "draws": lambda row: row.result == "D",
    "without-win": lambda row: row.result in ("D", "L"),
    "without-scoring": lambda row: row.goals_for == 0,
    "clean-sheets": lambda row: row.goals_against == 0,
}

#: What each run type must know about a match before it can say anything at
#: all. A match missing that figure breaks the run rather than extending it:
#: a sequence through a match nobody knows the outcome of is not a fact, it
#: is an assumption.
_REQUIRES = {
    "without-scoring": lambda row: row.goals_for is not None,
    "clean-sheets": lambda row: row.goals_against is not None,
}

#: Run types that a supporter counts as a drought rather than an achievement.
#: For these the interesting figure is the wait — from the last win to the
#: next, not merely across the barren matches themselves.
_GAPS = ("without-win", "without-scoring")


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
    kind: str
    length: int
    start: Match
    end: Match
    #: The matches either side of the run, where the record has them. A run
    #: at either end of the record has nothing beyond it.
    before: Match | None = None
    after: Match | None = None

    @property
    def bounded(self) -> bool:
        """Whether `days` is the whole answer rather than a lower bound.

        Only a drought can be open-ended: it is measured between the matches
        that ended the drought either side, and those may be missing — off
        the end of the record, or unplayable because nobody recorded the
        result. A run measured across its own matches is bounded by
        definition.
        """
        if self.kind not in _GAPS:
            return True
        known = _REQUIRES.get(self.kind, lambda row: row.result is not None)
        return all(match is not None and known(match)
                   for match in (self.before, self.after))

    @property
    def days(self) -> int:
        """How long it lasted. A lower bound when `bounded` is false."""
        first, last = self.start, self.end
        if self.bounded and self.kind in _GAPS:
            first, last = self.before, self.after
        return (date.fromisoformat(last.date) - date.fromisoformat(first.date)).days

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


def _scan(matches: list[Match], of: str):
    """Every run of `of`, in the order they were played.

    Each run carries the matches either side of it, so a drought can be
    measured from the win that preceded it to the win that ended it.
    """
    continues = _CONTINUES[of]
    known = _REQUIRES.get(of, lambda row: row.result is not None)
    current: list[Match] = []
    before: Match | None = None

    for index, match in enumerate(matches):
        if known(match) and continues(match):
            if not current:
                before = matches[index - 1] if index else None
            current.append(match)
            continue
        if current:
            yield Run(kind=of, length=len(current), start=current[0],
                      end=current[-1], before=before, after=match)
            current = []

    if current:
        yield Run(kind=of, length=len(current), start=current[0],
                  end=current[-1], before=before, after=None)


def longest(matches: list[Match], of: str) -> Run | None:
    """The longest run of `of`. Returns None if there is never one.

    Ties go to the earlier run, which is what `max` does with the runs
    arriving in the order they were played.
    """
    return max(_scan(matches, of), key=lambda run: run.length, default=None)


def all_runs(matches: list[Match], of: str, minimum: int = 2) -> list[Run]:
    """Every run of at least `minimum`, longest first."""
    return sorted((run for run in _scan(matches, of) if run.length >= minimum),
                  key=lambda run: (-run.length, run.start.date))
