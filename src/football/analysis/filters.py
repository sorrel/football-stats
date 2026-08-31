"""The filter vocabulary shared by every analysis command.

One filter set, many questions. "The biggest win, in the FA Cup, away, in the
1980s" is a question and four filters rather than a command of its own, which
is why there is no combinatorial explosion of commands here.

Every filter compiles to a parameterised fragment: the column name comes from
this module, the value is bound. A filter that interpolated its value into the
SQL would be an injection with extra steps.
"""

from __future__ import annotations

from dataclasses import dataclass, field

#: Types that group several competitions. A cup is its own type — see
#: `sources.engsoccer.competition_type` — so `--type` cannot merge the FA Cup
#: with the League Cup, which would be nobody's question.
GROUPING_TYPES = ("league", "play-off", "europe")

SIDES = ("home", "away", "neutral")

RUN_TYPES = ("unbeaten", "wins", "losses", "draws", "without-win", "clean-sheets")


@dataclass(frozen=True)
class Filters:
    """What subset of matches a question is being asked about."""

    #: Required. There is deliberately no default: once a second club exists,
    #: defaulting would answer a question about one club with another's
    #: record — a wrong answer that looks right.
    club: str
    competition: str | None = None
    tier: int | None = None
    type: str | None = None
    opponent: str | None = None
    venue: str | None = None
    side: str | None = None
    season_from: str | None = None
    season_to: str | None = None
    day: str | None = None
    english_league_only: bool = False
    extra: tuple[str, ...] = field(default_factory=tuple)

    def where(self) -> tuple[str, list]:
        """Compile to a WHERE clause and its bound parameters.

        The clause always constrains `cm.club`, so every question is asked
        from one club's point of view — which is what makes `goals_for` and
        `result` meaningful.
        """
        clauses = ["cm.club = ?"]
        params: list = [self.club]

        if self.competition:
            clauses.append("cm.competition = ?")
            params.append(self.competition)
        if self.tier is not None:
            clauses.append("m.tier = ?")
            params.append(self.tier)
        if self.type:
            clauses.append("comp.type = ?")
            params.append(self.type)
        if self.opponent:
            clauses.append("cm.opponent = ?")
            params.append(self.opponent)
        if self.venue:
            clauses.append("cm.venue = ?")
            params.append(self.venue)
        if self.side == "neutral":
            clauses.append("cm.neutral = 1")
        elif self.side == "home":
            clauses.append("cm.home_or_away = 'H' AND COALESCE(cm.neutral, 0) = 0")
        elif self.side == "away":
            clauses.append("cm.home_or_away = 'A' AND COALESCE(cm.neutral, 0) = 0")
        if self.season_from:
            clauses.append("cm.season >= ?")
            params.append(self.season_from)
        if self.season_to:
            clauses.append("cm.season <= ?")
            params.append(self.season_to)
        if self.day:
            clauses.append("cm.day_of_week = ?")
            params.append(self.day.capitalize())
        if self.english_league_only:
            clauses.append("opp.english_league = 1")

        clauses.extend(self.extra)
        return " AND ".join(clauses), params

    def describe(self) -> str:
        """A human summary of what is being counted, for the report heading."""
        parts = []
        if self.competition:
            parts.append(self.competition.replace("-", " "))
        if self.tier is not None:
            parts.append(f"tier {self.tier}")
        if self.type:
            parts.append(self.type.replace("-", " "))
        if self.opponent:
            parts.append(f"against {self.opponent.replace('-', ' ')}")
        if self.venue:
            parts.append(f"at {self.venue.replace('-', ' ')}")
        if self.side:
            parts.append(self.side)
        if self.day:
            parts.append(f"on a {self.day.capitalize()}")
        if self.season_from or self.season_to:
            parts.append(f"{self.season_from or 'the start'} to "
                         f"{self.season_to or 'now'}")
        if self.english_league_only:
            parts.append("against League clubs only")
        return ", ".join(parts) if parts else "all matches"


#: Every analysis query starts from this. The joins are what let a filter
#: reach `competitions.tier` and `clubs.english_league`.
FROM_CLAUSE = """
FROM club_matches cm
JOIN matches m ON m.match_id = cm.match_id
LEFT JOIN competitions comp ON comp.slug = cm.competition
LEFT JOIN clubs opp ON opp.slug = cm.opponent
"""


def select(columns: str, filters: Filters, order: str = "", limit: int | None = None
           ) -> tuple[str, list]:
    """Build a full statement for `columns` under `filters`."""
    where, params = filters.where()
    sql = f"SELECT {columns} {FROM_CLAUSE} WHERE {where}"
    if order:
        sql += f" ORDER BY {order}"
    if limit is not None:
        sql += " LIMIT ?"
        params = [*params, limit]
    return sql, params
