"""Turn parsed openfootball fixtures into canonical match rows.

This source names clubs its own way — "Middlesbrough FC" where the primary
source says "Middlesbrough" — so every name is resolved against the clubs we
already hold rather than slugified and hoped for. A name that cannot be
resolved is reported, never invented: inventing one would quietly create a
second row for a club we already have.
"""

from __future__ import annotations

from collections.abc import Iterable

import re

from football.ids import match_id, slugify
from football.parse.base import blank_row
from football.schema import MATCHES
from football.sources.openfootball import Fixture

SOURCE = "openfootball"

#: European files suffix every club with its country: "AEK Athen (GRE)".
_COUNTRY_CODE = re.compile(r"\s*\(([A-Z]{3})\)\s*$")

#: The codes we actually meet. Anything else keeps its code as the country,
#: which is honest — a wrong country name would be worse than a code.
COUNTRIES = {
    "ENG": "England", "SCO": "Scotland", "WAL": "Wales", "NIR": "Northern Ireland",
    "IRL": "Republic of Ireland", "GRE": "Greece", "NED": "Netherlands",
    "FRA": "France", "ITA": "Italy", "ESP": "Spain", "GER": "Germany",
    "POR": "Portugal", "BEL": "Belgium", "SRB": "Serbia", "TUR": "Turkey",
    "AUT": "Austria", "SUI": "Switzerland", "CZE": "Czech Republic",
    "DEN": "Denmark", "NOR": "Norway", "SWE": "Sweden", "POL": "Poland",
    "UKR": "Ukraine", "CRO": "Croatia", "ROU": "Romania", "HUN": "Hungary",
    "BUL": "Bulgaria", "CYP": "Cyprus", "ISR": "Israel", "AZE": "Azerbaijan",
    "KAZ": "Kazakhstan", "SVK": "Slovakia", "SVN": "Slovenia", "MDA": "Moldova",
}

#: The competition names this source uses, mapped to our slugs.
COMPETITIONS = {
    "English EFL Cup": "league-cup",
    "English League Cup": "league-cup",
    "English FA Cup": "fa-cup",
    "UEFA Europa League": "europa-league",
    "UEFA Champions League": "champions-league",
    "UEFA Europa Conference League": "conference-league",
    # The files use both names across seasons.
    "UEFA Conference League": "conference-league",
}

#: Suffixes this source adds that our names do not carry. Tried in order.
_SUFFIXES = (" fc", " afc")


def split_country(name: str) -> tuple[str, str]:
    """Separate "AEK Athen (GRE)" into the club name and its country."""
    match = _COUNTRY_CODE.search(name)
    if not match:
        return name.strip(), ""
    code = match.group(1)
    return name[: match.start()].strip(), COUNTRIES.get(code, code)


def candidate_slugs(name: str) -> list[str]:
    """The slugs a club name might correspond to, best guess first."""
    lowered = split_country(name)[0]
    candidates = [slugify(lowered)]
    for suffix in _SUFFIXES:
        if lowered.lower().endswith(suffix):
            candidates.append(slugify(lowered[: -len(suffix)]))
    # "AFC Bournemouth" -> "bournemouth"
    if lowered.lower().startswith("afc "):
        candidates.append(slugify(lowered[4:]))
    return candidates


def resolve(name: str, known: set[str], aliases: dict[str, str] | None = None) -> str:
    """The slug for `name`, or "" if we cannot say.

    Returning "" rather than a fresh slug is the point: an unrecognised name
    is a question for a person, not a new club.
    """
    plain = split_country(name)[0]
    if aliases and plain in aliases:
        return aliases[plain]
    for candidate in candidate_slugs(name):
        if candidate in known:
            return candidate
    return ""


#: The numbered rounds run back a century in both domestic cups, so the
#: number is canonical there — but the round of 16 is a *different* number in
#: each: the FA Cup's fifth round and the League Cup's fourth. European
#: rounds have no numbers and keep their names.
_CANONICAL_ROUNDS = {
    "fa-cup": {"Round of 16": "Round 5"},
    # engsoccerdata numbers this competition to round 5 and names only the
    # semi-final and final, so round 5 is the quarter-final there.
    "league-cup": {"Round of 16": "Round 4", "Quarter-final": "Round 5"},
}


def canonical_round(competition: str, name: str) -> str:
    """One name per round, so two sources cannot disagree about it."""
    return _CANONICAL_ROUNDS.get(competition, {}).get(name, name)


def to_match(fixture: Fixture, season: str, competition: str,
             home_slug: str, away_slug: str) -> dict[str, str]:
    """Build one canonical row from a parsed fixture."""
    row = blank_row(MATCHES)
    row.update({
        "match_id": match_id(fixture.date, home_slug, away_slug),
        "date": fixture.date,
        "kickoff": fixture.kickoff,
        "season": season,
        "home_club": home_slug,
        "away_club": away_slug,
        "competition": competition,
        "round": canonical_round(competition, fixture.round),
        "ht_home": fixture.ht[0], "ht_away": fixture.ht[1],
        "ft_home": fixture.ft[0], "ft_away": fixture.ft[1],
        "aet_home": fixture.aet[0], "aet_away": fixture.aet[1],
        "pens_home": fixture.pens[0], "pens_away": fixture.pens[1],
        "status": "played",
        "source": SOURCE,
    })
    return row


def convert(
    fixtures: Iterable[Fixture],
    season: str,
    competition_name: str,
    known_clubs: set[str],
    club: str,
    aliases: dict[str, str] | None = None,
) -> tuple[list[dict[str, str]], list[str]]:
    """Convert the fixtures involving `club`. Returns (rows, unresolved names)."""
    competition = COMPETITIONS.get(competition_name, "")
    rows: list[dict[str, str]] = []
    unresolved: list[str] = []
    if not competition:
        return rows, [f"unknown competition: {competition_name}"]

    for fixture in fixtures:
        home = resolve(fixture.home, known_clubs, aliases)
        away = resolve(fixture.away, known_clubs, aliases)
        if club not in (home, away):
            continue
        if not home or not away:
            unresolved.append(fixture.home if not home else fixture.away)
            continue
        rows.append(to_match(fixture, season, competition, home, away))

    return rows, sorted(set(unresolved))


def merge_into(
    existing: list[dict[str, str]],
    incoming: list[dict[str, str]],
) -> tuple[list[dict[str, str]], int, int]:
    """Add new matches, and fill only blank fields on ones we already hold.

    A plain upsert would replace the whole row, discarding attendance, venue
    and replay links the primary source supplied and this one does not carry.
    Returns (rows to write, added, enriched).
    """
    by_id = {row["match_id"]: row for row in existing}
    to_write: list[dict[str, str]] = []
    added = enriched = 0

    for row in incoming:
        current = by_id.get(row["match_id"])
        if current is None:
            to_write.append(row)
            added += 1
            continue
        changed = False
        for name, value in row.items():
            if value != "" and current.get(name, "") == "":
                current[name] = value
                changed = True
        if changed:
            if SOURCE not in current["source"]:
                current["source"] = f"{current['source']}+{SOURCE}"
            to_write.append(current)
            enriched += 1

    return to_write, added, enriched
