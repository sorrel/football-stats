"""Import final league positions from the Fjelstul English Football Database.

Licence: CC-BY-SA 4.0 — attribution required, share-alike on redistribution.
Recorded in the README because it differs from everything else in this tree.

Only position, points and point adjustment are taken. Played, won, drawn,
lost and goals are all computable from the matches we already hold, and a
second copy is a second thing that can be wrong.

The competition and tier come from our own matches rather than from the
source's division name: "First Division" was tier 1 until 1992 and tier 2
after, so the name alone cannot say which competition a season was.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping

from football.parse.base import blank_row
from football.schema import SEASONS
from football.sources.common import clean as _clean
from football.sources.common import season_label

SOURCE = "fjelstul"


def season_id(season: str, club: str, competition: str) -> str:
    """The identifier for one club's season in one competition."""
    return f"{season}_{club}_{competition}"


def convert(
    records: Iterable[Mapping[str, str]],
    club_names: str | Iterable[str],
    club_slug: str,
    league_seasons: Mapping[str, tuple[str, str]],
) -> tuple[list[dict[str, str]], list[str]]:
    """Convert this club's standings rows.

    `club_names` is every name the club has had. Clubs were renamed — Arsenal
    were Woolwich Arsenal until 1914, Manchester United were Newton Heath —
    and this source uses the name of the day, so matching only the current
    one silently loses those seasons.

    `league_seasons` maps a season label to the (competition, tier) that club
    played its league matches in, taken from our own data. A season absent
    from it is reported rather than guessed.
    """
    if isinstance(club_names, str):
        club_names = [club_names]
    wanted = {name.strip() for name in club_names if name and name.strip()}
    rows: list[dict[str, str]] = []
    skipped: list[str] = []

    for record in records:
        if record.get("team_name", "").strip() not in wanted:
            continue
        season = season_label(record["season"])
        known = league_seasons.get(season)
        if known is None:
            skipped.append(season)
            continue
        competition, tier = known

        row = blank_row(SEASONS)
        row.update({
            "season_id": season_id(season, club_slug, competition),
            "club": club_slug,
            "season": season,
            "competition": competition,
            "tier": tier,
            "position": _clean(record.get("position", "")),
            "points": _clean(record.get("points", "")),
            "point_adjustment": _clean(record.get("point_adjustment", "")),
            "source": SOURCE,
        })
        rows.append(row)

    return rows, sorted(set(skipped))
