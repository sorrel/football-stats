"""Aggregate records: played, won, drawn, lost, and head-to-head.

Uses `result` — the outcome after 90 minutes — because that is what a league
record has always counted. Sequence questions use `final_result` instead; see
`analysis.runs`.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Sequence
from dataclasses import dataclass

from football.analysis.filters import FROM_CLAUSE, Filters, select


@dataclass(frozen=True)
class Record:
    played: int
    won: int
    drawn: int
    lost: int
    goals_for: int
    goals_against: int
    #: Matches with no recorded score, excluded from the goal totals. Reported
    #: rather than hidden: a goal total drawn from part of the data, presented
    #: as if from all of it, is a wrong answer that looks right.
    without_score: int

    @property
    def win_percentage(self) -> float:
        return 100.0 * self.won / self.played if self.played else 0.0

    @property
    def goal_difference(self) -> int:
        return self.goals_for - self.goals_against

    def summary(self) -> str:
        return (f"P{self.played} W{self.won} D{self.drawn} L{self.lost} "
                f"F{self.goals_for} A{self.goals_against} "
                f"({self.win_percentage:.1f}%)")


#: Declared once: the overall record and a breakdown of it must count the
#: same things, or the rows will not add up to the table above them.
_RECORD_COLUMNS = """
    COUNT(*) AS played,
    SUM(cm.result = 'W') AS won,
    SUM(cm.result = 'D') AS drawn,
    SUM(cm.result = 'L') AS lost,
    COALESCE(SUM(cm.goals_for), 0) AS goals_for,
    COALESCE(SUM(cm.goals_against), 0) AS goals_against,
    SUM(cm.goals_for IS NULL) AS without_score
"""


def _record(row: Sequence, at: int = 0) -> Record:
    """Build a record from seven columns of `row`, starting at `at`."""
    return Record(
        played=row[at] or 0, won=row[at + 1] or 0, drawn=row[at + 2] or 0,
        lost=row[at + 3] or 0, goals_for=row[at + 4] or 0,
        goals_against=row[at + 5] or 0, without_score=row[at + 6] or 0,
    )


def record(conn: sqlite3.Connection, filters: Filters) -> Record:
    """The overall record under these filters."""
    sql, params = select(_RECORD_COLUMNS, filters)
    return _record(conn.execute(sql, params).fetchone())


@dataclass(frozen=True)
class CupExtras:
    """What the cup matches under a filter amounted to.

    A cup draw is not the end of the contest the way a league draw is the
    end of the match: before the 1990s it was replayed, a two-legged contest
    has a second leg, and a modern one goes to extra time and penalties.
    Counting only matches makes three matches over two contests look like
    three contests. ("Tie" is the football word, and is avoided: it reads as
    a synonym for a draw, which is the very thing being explained.)
    """

    #: Matches that begin a contest — neither a replay nor a second leg. The
    #: contest is counted where it started: the ground the draw was at.
    contests: int
    replays: int
    extra_time: int
    penalties: int


_EXTRAS_COLUMNS = """
    SUM(COALESCE(m.is_replay, 0) = 0 AND COALESCE(m.leg, 1) = 1) AS contests,
    SUM(COALESCE(m.is_replay, 0) = 1) AS replays,
    SUM(m.aet_home IS NOT NULL) AS extra_time,
    SUM(m.pens_home IS NOT NULL) AS penalties
"""


def _extras(row: Sequence, at: int = 0) -> CupExtras:
    return CupExtras(contests=row[at] or 0, replays=row[at + 1] or 0,
                     extra_time=row[at + 2] or 0, penalties=row[at + 3] or 0)


def cup_extras(conn: sqlite3.Connection, filters: Filters) -> CupExtras:
    """How the cup contests under these filters were played out."""
    sql, params = select(_EXTRAS_COLUMNS, filters)
    return _extras(conn.execute(sql, params).fetchone())


@dataclass(frozen=True)
class Group:
    """One line of a breakdown: a round of a cup, or a division."""

    label: str
    #: The earliest match in the group, so divisions can be put in the order
    #: they were played in rather than alphabetically.
    first_date: str
    record: Record
    extras: CupExtras


def breakdown(conn: sqlite3.Connection, filters: Filters,
              expression: str) -> list[Group]:
    """The record under these filters, split by `expression`.

    A group with nothing in it cannot appear: the split is over the matches
    that were played, so a round never reached is simply absent rather than
    a row of zeros.
    """
    where, params = filters.where()
    sql = (f"SELECT {expression} AS grp, MIN(cm.date) AS first_date, "
           f"{_RECORD_COLUMNS}, {_EXTRAS_COLUMNS} {FROM_CLAUSE} "
           f"WHERE {where} GROUP BY grp")
    return [Group(label=row[0], first_date=row[1],
                  record=_record(row, 2), extras=_extras(row, 9))
            for row in conn.execute(sql, params) if row[0]]


def meetings(conn: sqlite3.Connection, filters: Filters) -> list[tuple]:
    """Every meeting under these filters, oldest first."""
    sql, params = select(
        """
        cm.date, cm.season, cm.competition, cm.round, cm.home_or_away,
        cm.goals_for, cm.goals_against, cm.result, cm.attendance
        """,
        filters,
        order="cm.date",
    )
    return conn.execute(sql, params).fetchall()
