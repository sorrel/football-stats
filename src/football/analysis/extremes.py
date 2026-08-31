"""The biggest, the highest, the most.

Every extreme here depends on a column that may be unknown, so each result
carries the coverage it was drawn from. A record attendance computed from
0.3% of matches is not wrong so much as misleading, and the honest fix is to
say so alongside the figure rather than to withhold it.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from football.analysis.filters import Filters, select

#: What each extreme orders by, and the column its coverage depends on.
_MEASURES = {
    "margin": ("(cm.goals_for - cm.goals_against) DESC, cm.goals_for DESC",
               "cm.goals_for"),
    "defeat": ("(cm.goals_against - cm.goals_for) DESC, cm.goals_against DESC",
               "cm.goals_for"),
    "goals": ("(cm.goals_for + cm.goals_against) DESC", "cm.goals_for"),
    "scored": ("cm.goals_for DESC", "cm.goals_for"),
    "attendance": ("cm.attendance DESC", "cm.attendance"),
}

MEASURES = tuple(_MEASURES)

#: Wins and losses, each with its own order and its own condition on the
#: score. Draws are not among them: a draw has no margin or defeat to rank
#: by, so it falls to `high_scoring` instead, alongside any win or loss that
#: was high-scoring without being one of the biggest.
_RESULTS = {
    "wins": (_MEASURES["margin"][0], "cm.goals_for > cm.goals_against"),
    "losses": (_MEASURES["defeat"][0], "cm.goals_against > cm.goals_for"),
}

RESULTS = tuple(_RESULTS)

#: A match's opponent and competition rendered by name, falling back to the
#: slug reformatted the way `club_name` does, for the rare match whose
#: opponent or competition is not itself in the database. `match_id` is
#: last and never displayed: it is how a caller recognises a match it has
#: already shown, without disturbing the columns a table renders.
_ROW_COLUMNS = """
cm.date, cm.season,
COALESCE(comp.name, REPLACE(cm.competition, '-', ' ')) AS competition,
COALESCE(opp.name, REPLACE(cm.opponent, '-', ' ')) AS opponent,
cm.home_or_away, cm.goals_for, cm.goals_against, cm.attendance, cm.match_id
"""


@dataclass(frozen=True)
class Coverage:
    """How much of the data an answer actually rests on."""

    available: int
    total: int

    @property
    def is_partial(self) -> bool:
        return self.available < self.total

    def describe(self) -> str:
        if not self.total:
            return "no matches"
        share = 100.0 * self.available / self.total
        return (f"based on {self.available:,} of {self.total:,} matches "
                f"({share:.1f}%) with this recorded")


def coverage(conn: sqlite3.Connection, filters: Filters, column: str) -> Coverage:
    sql, params = select(
        f"SUM({column} IS NOT NULL), COUNT(*)", filters)
    available, total = conn.execute(sql, params).fetchone()
    return Coverage(available=available or 0, total=total or 0)


def _top_matches(conn: sqlite3.Connection, filters: Filters, order: str, limit: int
                  ) -> list[tuple]:
    sql, params = select(_ROW_COLUMNS, filters, order=order, limit=limit)
    return conn.execute(sql, params).fetchall()


def extremes(conn: sqlite3.Connection, filters: Filters, by: str, limit: int = 10
             ) -> tuple[list[tuple], Coverage]:
    """The top `limit` matches by `by`, with the coverage behind the answer."""
    order, column = _MEASURES[by]
    constrained = Filters(**{**filters.__dict__,
                             "extra": (*filters.extra, f"{column} IS NOT NULL")})
    return _top_matches(conn, constrained, order, limit), coverage(conn, filters, column)


def extremes_by_result(conn: sqlite3.Connection, filters: Filters, result: str,
                        limit: int = 10) -> tuple[list[tuple], Coverage]:
    """The top `limit` wins or losses, with the coverage behind them.

    Coverage is judged against every match under `filters`, not just the ones
    that qualified: a match with no recorded score cannot be classified as a
    win or a loss at all, so the honest denominator is everything that might
    have been one, not the subset that could be shown to be.
    """
    order, condition = _RESULTS[result]
    constrained = Filters(**{**filters.__dict__,
                             "extra": (*filters.extra, condition,
                                       "cm.goals_for IS NOT NULL")})
    return (_top_matches(conn, constrained, order, limit),
            coverage(conn, filters, "cm.goals_for"))


def high_scoring(conn: sqlite3.Connection, filters: Filters,
                  exclude_ids: frozenset[str], limit: int = 10
                  ) -> tuple[list[tuple], Coverage]:
    """The top `limit` matches by total goals, aside from `exclude_ids`.

    A 6-5 win is nobody's biggest win by margin, but at eleven goals it is
    still the kind of match this is asking about — so a match is left out
    here only because it has already been shown as one of the biggest wins
    or losses, never because of its own result.
    """
    order, column = _MEASURES["goals"]
    constrained = Filters(**{**filters.__dict__,
                             "extra": (*filters.extra, f"{column} IS NOT NULL")})
    # Fetched to spare: at most `len(exclude_ids)` of the extra rows can be
    # ones already excluded, so this always leaves at least `limit` behind.
    fetched = _top_matches(conn, constrained, order, limit + len(exclude_ids))
    rows = [row for row in fetched if row[-1] not in exclude_ids][:limit]
    return rows, coverage(conn, filters, column)
