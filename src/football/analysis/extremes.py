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


def extremes(conn: sqlite3.Connection, filters: Filters, by: str, limit: int = 10
             ) -> tuple[list[tuple], Coverage]:
    """The top `limit` matches by `by`, with the coverage behind the answer."""
    order, column = _MEASURES[by]
    constrained = Filters(**{**filters.__dict__,
                             "extra": (*filters.extra, f"{column} IS NOT NULL")})
    sql, params = select(
        """
        cm.date, cm.season, cm.competition, cm.opponent, cm.home_or_away,
        cm.goals_for, cm.goals_against, cm.attendance
        """,
        constrained,
        order=order,
        limit=limit,
    )
    return conn.execute(sql, params).fetchall(), coverage(conn, filters, column)
