"""Import the engsoccerdata league and FA Cup datasets.

Two files, two shapes, one output. The league file carries results only; the
FA Cup file adds extra time, penalties, venue, attendance and neutral grounds.
Neither carries half-time scores or card counts, so those stay empty — which
means unknown, not zero.

One trap worth stating plainly: in the FA Cup file the `FT` column holds the
score at the *end of the match*, so when `aet` is set it is the score after
120 minutes, not 90. Filing that as `ft_*` would break the running-total
convention and quietly corrupt every "goals in extra time" figure. The
90-minute score is genuinely unknown in that case, so `ft_*` is left empty and
the score is recorded as `aet_*`.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Iterator

from football.ids import match_id, slugify
from football.parse.base import blank_row
from football.sources.common import (
    clean, parse_attendance, parse_score, season_label)
from football.schema import CLUBS, COMPETITIONS, MATCHES, VENUES

SOURCE = "engsoccerdata"



#: Round labels vary between files and even within one: "Final" and "final",
#: "Semi-final" and "semi". Normalised to one spelling, or the same round
#: reads as two and both tie-grouping and round queries break.
_ROUND_NAMES = {
    "f": "Final", "final": "Final",
    "s": "Semi-final", "semi": "Semi-final", "semi-final": "Semi-final",
    "sf": "Semi-final",
    "quarter-final": "Quarter-final", "qf": "Quarter-final",
    "prelim": "Preliminary Round", "preliminary": "Preliminary Round",
    "q": "Qualifying Round",
}

#: Tier names change while the tier stays the same. The season a competition
#: was renamed is the boundary; `season` here is the starting year.
_TIER_NAMES: dict[int, tuple[tuple[int, str], ...]] = {
    1: ((1992, "Premier League"), (0, "Division One")),
    2: ((2004, "Championship"), (1992, "Division One"), (0, "Division Two")),
    3: ((2004, "League One"), (1992, "Division Two"), (0, "Division Three")),
    4: ((2004, "League Two"), (1992, "Division Three"), (0, "Division Four")),
}


def _absent(value: str) -> bool:
    return not clean(value)


#: Re-exported so the rest of this module reads as it always did.
_clean = clean


#: The Third Division was regionalised from 1921-22 to 1957-58. Both halves
#: were tier 3, so the tier alone cannot name the competition — the source's
#: own division code can.
_REGIONAL = {
    "3S": ("division-three-south", "Third Division South"),
    "3N": ("division-three-north", "Third Division North"),
}

#: Before the play-off system began in 1986-87, promotion and relegation
#: between Divisions One and Two was sometimes settled by a Test Match
#: series between the clubs concerned — not tied to a single tier the way
#: every other play-off is, so engsoccerdata marks the "division" column
#: with this literal string rather than a number.
_TEST_MATCH = "test match"
_TEST_MATCH_SLUG = "test-matches"


def league_competition(tier: str, season_start: str | int,
                       division: str = "") -> tuple[str, str, int]:
    """The competition slug, display name and tier for a league match."""
    tier_number = int(tier)
    year = int(season_start)
    regional = _REGIONAL.get(_clean(division).upper())
    if regional:
        return regional[0], regional[1], tier_number
    for boundary, name in _TIER_NAMES[tier_number]:
        if year >= boundary:
            return slugify(name), name, tier_number
    raise ValueError(f"no name for tier {tier} in {season_start}")


def round_name(code: str) -> str:
    """Normalise a round label to one spelling."""
    code = _clean(code)
    lowered = code.lower()
    if lowered in _ROUND_NAMES:
        return _ROUND_NAMES[lowered]
    if code.isdigit():
        return f"Round {code}"
    return code


def parse_venue(text: str) -> tuple[str, str, str]:
    """Split "Wembley (original), London" into slug, name and city."""
    if _absent(text):
        return "", "", ""
    name, _, city = text.partition(",")
    return slugify(name), name.strip(), city.strip()


#: Play-offs belong to a division but are not league matches — counting them
#: as such would distort every league record. They get their own competition
#: per tier, named for the era, e.g. "Championship Play-offs".
def playoff_competition(tier: str, season_start: str | int) -> tuple[str, str]:
    if _clean(tier).lower() == _TEST_MATCH:
        return _TEST_MATCH_SLUG, "Test Matches"
    _, league_name, _ = league_competition(tier, season_start)
    name = f"{league_name} Play-offs"
    return slugify(name), name


def _base_row(date: str, season: str, home: str, away: str, competition: str) -> dict:
    row = blank_row(MATCHES)
    home_slug, away_slug = slugify(home), slugify(away)
    row.update({
        "match_id": match_id(date, home_slug, away_slug),
        "date": date,
        "season": season,
        "home_club": home_slug,
        "away_club": away_slug,
        "competition": competition,
        "status": "played",
        "source": SOURCE,
    })
    return row


def league_match(record: dict[str, str]) -> dict[str, str]:
    """Convert one league row."""
    season = season_label(record["Season"])
    slug, _, _ = league_competition(record["tier"], record["Season"],
                                    record.get("division", ""))
    row = _base_row(record["Date"], season, record["home"], record["visitor"], slug)
    row["tier"] = _clean(record["tier"])
    row["ft_home"] = _clean(record["hgoal"])
    row["ft_away"] = _clean(record["vgoal"])
    return row


def is_real_match(record: dict[str, str]) -> bool:
    """Byes and disqualifications are recorded as ties but were never played."""
    return _absent(record.get("nonmatch", "")) and not _absent(record.get("FT", ""))


def facup_match(record: dict[str, str]) -> dict[str, str]:
    """Convert one FA Cup row."""
    season = season_label(record["Season"])
    row = _base_row(record["Date"], season, record["home"], record["visitor"], "fa-cup")
    row["round"] = round_name(record["round"])
    row["attendance"] = parse_attendance(record["attendance"])
    row["neutral"] = "true" if not _absent(record.get("neutral", "")) else ""
    # The 1945-46 competition was played over two legs, so a second meeting
    # is not necessarily a replay. The source says which it is.
    row["leg"] = _leg_from_tie(record.get("tie", ""))
    row["is_replay"] = "true" if _is_replay_tie(record.get("tie", "")) else ""

    venue_slug, _, _ = parse_venue(record.get("Venue", ""))
    row["venue"] = venue_slug

    home_goals, away_goals = parse_score(record["FT"])
    if _absent(record.get("aet", "")):
        row["ft_home"], row["ft_away"] = home_goals, away_goals
    else:
        # `FT` is the score after extra time; the 90-minute score is unknown.
        row["aet_home"], row["aet_away"] = home_goals, away_goals

    if not _absent(record.get("pen", "")):
        row["pens_home"] = _clean(record.get("hp", ""))
        row["pens_away"] = _clean(record.get("vp", ""))

    return row


def _tie_group(row: dict[str, str]) -> tuple:
    """What makes two rows the same tie: same round, same leg, same clubs."""
    return (row["season"], row["competition"], row["round"], row["leg"],
            *sorted((row["home_club"], row["away_club"])))


def link_replays(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    """Point each replay at the tie it replays, using the source's own marking.

    Preferred over inferring from dates: a two-legged tie also has two dates
    and the same two clubs, so date order alone cannot tell a second leg from
    a replay. `leg` is part of the grouping for the same reason.
    """
    originals = {_tie_group(row): row for row in rows if row["is_replay"] != "true"}
    for row in rows:
        if row["is_replay"] == "true":
            original = originals.get(_tie_group(row))
            if original is not None:
                row["replay_of"] = original["match_id"]
    return rows


def playoff_match(record: dict[str, str]) -> dict[str, str]:
    """Convert one play-off row."""
    season = season_label(record["Season"])
    slug, _ = playoff_competition(record["division"], record["Season"])
    row = _base_row(record["Date"], season, record["home"], record["visitor"], slug)
    row["round"] = round_name(record["round"])
    # A Test Match decided promotion between two tiers at once, so no
    # single number belongs here — `tier` is a typed int column, and the
    # two sides' own tiers (htier/vtier) do not agree in general.
    division = _clean(record.get("division", ""))
    row["tier"] = "" if division.lower() == _TEST_MATCH else division
    row["leg"] = _leg_from_tie(record.get("tie", ""))
    row["is_replay"] = "true" if _is_replay_tie(record.get("tie", "")) else ""
    row["attendance"] = parse_attendance(record.get("attendance", ""))
    row["neutral"] = "true" if not _absent(record.get("neutral", "")) else ""
    row["venue"], _, _ = parse_venue(record.get("Venue", ""))
    _set_scores(row, record, pens_home="hp", pens_away="vp")
    return row


def leaguecup_match(record: dict[str, str]) -> dict[str, str]:
    """Convert one League Cup row."""
    season = season_label(record["Season"])
    row = _base_row(record["Date"], season, record["home"], record["visitor"],
                    "league-cup")
    row["round"] = round_name(record["round"])
    leg = _clean(record.get("leg", ""))
    row["leg"] = leg if leg in {"1", "2"} else ""
    row["is_replay"] = "true" if _is_replay_tie(record.get("tie", "")) else ""
    row["attendance"] = parse_attendance(record.get("attendance", ""))
    row["venue"], _, _ = parse_venue(record.get("Venue", ""))
    _set_scores(row, record)
    return row


def _leg_from_tie(tie: str) -> str:
    tie = _clean(tie).lower()
    return tie[3:] if tie.startswith("leg") and tie[3:] in {"1", "2"} else ""


def _is_replay_tie(tie: str) -> bool:
    return _clean(tie).lower().startswith("replay")


def _set_scores(row: dict[str, str], record: dict[str, str],
                pens_home: str = "", pens_away: str = "") -> None:
    """Fill the score columns, honouring the extra-time convention."""
    home, away = parse_score(record.get("FT", ""))
    if not home:
        home, away = _clean(record.get("hgoal", "")), _clean(record.get("vgoal", ""))
    if _absent(record.get("aet", "")):
        row["ft_home"], row["ft_away"] = home, away
    else:
        # `FT` is the score after extra time; 90 minutes is not recorded.
        row["aet_home"], row["aet_away"] = home, away
    if pens_home and not _absent(record.get("pen", "")):
        row["pens_home"] = _clean(record.get(pens_home, ""))
        row["pens_away"] = _clean(record.get(pens_away, ""))


def league_club_slugs(league_records: Iterable[dict[str, str]]) -> set[str]:
    """Every club that ever appeared in the league file.

    This is the authority for `english_league`: a club played in the English
    League if and only if it appears here. Cup opposition absent from this set
    is non-League and must not be flagged as a League club, or every "against
    League opposition" query is wrong.
    """
    slugs: set[str] = set()
    for record in league_records:
        slugs.add(slugify(record["home"]))
        slugs.add(slugify(record["visitor"]))
    return slugs


def clubs_from(
    rows: Iterable[dict[str, str]],
    names: dict[str, str],
    league_clubs: set[str] | None = None,
) -> list[dict]:
    """Build club rows for every club appearing in `rows`.

    `league_clubs` is the set from `league_club_slugs`. Without it nothing is
    claimed: `english_league` is left empty, meaning unknown, rather than
    asserting something we have not checked.
    """
    out = []
    for slug in sorted({r["home_club"] for r in rows} | {r["away_club"] for r in rows}):
        club = blank_row(CLUBS)
        if league_clubs is None:
            english = ""
        else:
            english = "true" if slug in league_clubs else "false"
        club.update({"slug": slug, "name": names.get(slug, slug),
                     "english_league": english, "country": "England"})
        out.append(club)
    return out


def venues_from(records: Iterable[dict[str, str]]) -> list[dict]:
    """Build venue rows from the FA Cup file's venue column."""
    seen: dict[str, dict[str, str]] = {}
    for record in records:
        slug, name, city = parse_venue(record.get("Venue", ""))
        if slug and slug not in seen:
            venue = blank_row(VENUES)
            venue.update({"slug": slug, "name": name, "city": city})
            seen[slug] = venue
    return [seen[slug] for slug in sorted(seen)]


#: Competitions whose type is a grouping rather than the competition itself.
#: Leagues are grouped because comparing tiers is meaningful; cups are not,
#: because the FA Cup and the League Cup are different competitions and a
#: combined figure is nobody's question.
_LEAGUE_SLUGS = frozenset(
    slugify(name) for names in _TIER_NAMES.values() for _, name in names
) | {"division-three-south", "division-three-north"}

_EUROPEAN = frozenset({"europa-league", "champions-league", "conference-league"})


def competition_type(slug: str) -> str:
    """The type of a competition, given its slug.

    A cup is its own type. Anything unrecognised is treated as a cup of its
    own, so a competition added later cannot land in a bucket with another.
    """
    if slug in _LEAGUE_SLUGS:
        return "league"
    if slug.endswith("play-offs") or slug == _TEST_MATCH_SLUG:
        return "play-off"
    if slug in _EUROPEAN:
        return "europe"
    return slug


#: Competitions whose display name is not derivable from the slug.
_SPECIAL_NAMES = {
    "fa-cup": "FA Cup",
    "league-cup": "League Cup",
    "europa-league": "UEFA Europa League",
    "champions-league": "UEFA Champions League",
    "conference-league": "UEFA Europa Conference League",
    _TEST_MATCH_SLUG: "Test Matches",
}


def competition_name(slug: str) -> str:
    """The display name for a competition slug.

    Title-casing the slug is not enough: it turns "division-three-south" into
    "Division Three South" rather than "Third Division South", and loses the
    hyphen in "Play-offs".
    """
    if slug in _SPECIAL_NAMES:
        return _SPECIAL_NAMES[slug]
    for regional_slug, name in _REGIONAL.values():
        # The slug and the name deliberately differ here — the competition is
        # "Third Division South" but sorts with the other division-three
        # slugs — so the stored slug is what must be compared.
        if regional_slug == slug:
            return name
    if slug.endswith("-play-offs"):
        base = competition_name(slug[: -len("-play-offs")])
        return f"{base} Play-offs"
    for names in _TIER_NAMES.values():
        for _, name in names:
            if slugify(name) == slug:
                return name
    return slug.replace("-", " ").title()


def competitions_from(rows: Iterable[dict[str, str]]) -> list[dict]:
    """Build competition rows for the competitions these matches name.

    The seasons a competition ran are deliberately left blank: this sees one
    club's matches from one source, so any span it computed would miss the
    seasons another source supplied and would be overwritten by the next
    club imported. The applier recomputes them from every match in the store.
    """
    spans: dict[str, list[str]] = {}
    for row in rows:
        spans.setdefault(row["competition"], []).append(row["season"])

    out = []
    for slug, seasons in sorted(spans.items()):
        competition = blank_row(COMPETITIONS)
        name = slug.replace("-", " ").title()
        # Deliberately not set here. A league's tier depends on the season,
        # not the name — Division One was tier 1 before 1992 and tier 2 after —
        # so it lives on the match, where the season is known.
        tier = ""
        competition.update({
            "slug": slug,
            "name": competition_name(slug),
            "type": competition_type(slug),
            "tier": tier,
            "first_season": "",
            "last_season": "",
        })
        out.append(competition)
    return out


def select_club(records: Iterable[dict[str, str]], club_name: str) -> Iterator[dict]:
    """Only the records in which `club_name` played."""
    for record in records:
        if club_name in (record["home"], record["visitor"]):
            yield record
