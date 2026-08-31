"""The single declaration of every stored column.

Adding a field is a one-line change here. `store` and `db` both derive their
columns from this module, so nothing else needs to know the column list.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class Field:
    name: str
    kind: str  # "text" | "int" | "bool" | "date" | "time"
    required: bool = False


@dataclass(frozen=True)
class Table:
    name: str
    key: str
    fields: tuple[Field, ...]

    def field_names(self) -> tuple[str, ...]:
        return tuple(f.name for f in self.fields)


MATCHES = Table(
    name="matches",
    key="match_id",
    fields=(
        Field("match_id", "text", required=True),
        Field("date", "date", required=True),
        Field("kickoff", "time"),
        Field("season", "text", required=True),
        Field("home_club", "text", required=True),
        Field("away_club", "text", required=True),
        Field("neutral", "bool"),
        Field("venue", "text"),
        Field("competition", "text", required=True),
        # The tier the competition sat at *in that season*. A match-level
        # field because the name is not enough: Division One was tier 1
        # until 1992 and tier 2 afterwards, so one slug spans two tiers.
        Field("tier", "int"),
        Field("round", "text"),
        Field("leg", "int"),
        Field("ht_home", "int"),
        Field("ht_away", "int"),
        Field("ft_home", "int"),
        Field("ft_away", "int"),
        Field("aet_home", "int"),
        Field("aet_away", "int"),
        Field("pens_home", "int"),
        Field("pens_away", "int"),
        Field("is_replay", "bool"),
        Field("replay_of", "text"),
        Field("attendance", "int"),
        Field("home_yellows", "int"),
        Field("away_yellows", "int"),
        Field("home_reds", "int"),
        Field("away_reds", "int"),
        Field("status", "text"),
        Field("abandoned_reason", "text"),
        # Which dataset this row came from. Not a URL — a short tag, so that
        # when two sources disagree the row can be adjudicated rather than
        # silently overwritten by whichever import ran last.
        Field("source", "text", required=True),
    ),
)

CLUBS = Table(
    name="clubs",
    key="slug",
    fields=(
        Field("slug", "text", required=True),
        Field("name", "text", required=True),
        Field("former_names", "text"),
        Field("english_league", "bool"),
        Field("country", "text"),
        # True once this club has been imported as the subject of a run.
        # Without it, a club present only as an opponent reports a "record"
        # of its handful of meetings with the clubs we do hold — formatted
        # exactly like a complete one.
        Field("imported", "bool"),
    ),
)

COMPETITIONS = Table(
    name="competitions",
    key="slug",
    fields=(
        Field("slug", "text", required=True),
        Field("name", "text", required=True),
        Field("type", "text", required=True),
        Field("tier", "int"),
        # Competitions start and end. Without these, "no League Cup ties in
        # 1955" cannot be told apart from "no data for 1955" — the first is a
        # fact, the second is a gap.
        Field("first_season", "text"),
        Field("last_season", "text"),
    ),
)

VENUES = Table(
    name="venues",
    key="slug",
    fields=(
        Field("slug", "text", required=True),
        Field("name", "text", required=True),
        Field("city", "text"),
        Field("club", "text"),
    ),
)

SEASONS = Table(
    name="seasons",
    key="season_id",
    fields=(
        Field("season_id", "text", required=True),
        Field("club", "text", required=True),
        Field("season", "text", required=True),
        Field("competition", "text", required=True),
        Field("tier", "int"),
        # Stored because they cannot be recomputed: the points-per-win rule
        # changed in 1981, and a deduction is external to the results.
        Field("position", "int"),
        Field("points", "int"),
        Field("point_adjustment", "int"),
        Field("source", "text", required=True),
    ),
)

TABLES = (CLUBS, COMPETITIONS, VENUES, SEASONS, MATCHES)
