"""Enrich existing matches with half-time scores, cards and kick-off times.

This source covers 1993 onwards and names clubs differently from the primary
source ("Brighton", not "Brighton & Hove Albion"). Importing it as matches
would therefore create a duplicate of every fixture under a different slug.

So it does not import matches at all. It *enriches* matches already present,
located by date and by which side our club played — which needs no club-name
mapping and cannot invent a fixture. Anything it cannot place is reported
rather than inserted.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping

SOURCE = "football-data"

#: Division code to competition slug. This source covers 1993 onwards, by
#: which time these four names were settled, so no era mapping is needed.
COMPETITIONS = {"E0": "premier-league", "E1": "championship",
                "E2": "league-one", "E3": "league-two"}

#: The division codes are the tiers, and have been throughout this source's
#: coverage (1993 onwards).
TIERS = {"E0": "1", "E1": "2", "E2": "3", "E3": "4"}

#: The divisions Brighton have played in since 1993.
DIVISIONS = ("E0", "E1", "E2", "E3")

#: Fields this source can supply, mapped to the columns they fill.
_ENRICHMENT = {
    "HTHG": "ht_home", "HTAG": "ht_away",
    "HY": "home_yellows", "AY": "away_yellows",
    "HR": "home_reds", "AR": "away_reds",
}


def records(text: str) -> list[dict[str, str]]:
    """Parse one downloaded file into records.

    The leading byte-order mark must be stripped: some seasons carry one and
    some do not, and left in place it becomes part of the first column's name,
    so `Div` reads as empty and the whole season is silently discarded.
    """
    import csv as _csv
    import io as _io

    if not text.strip():
        return []
    return list(_csv.DictReader(_io.StringIO(text.lstrip("\ufeff"))))


def season_urls(start_year: int, base: str) -> list[str]:
    """The four divisional files for one season, e.g. 1993 -> .../9394/E0.csv."""
    code = f"{start_year % 100:02d}{(start_year + 1) % 100:02d}"
    return [f"{base}/{code}/{division}.csv" for division in DIVISIONS]


def parse_date(text: str) -> str:
    """Convert DD/MM/YY or DD/MM/YYYY to ISO. Returns "" if unreadable."""
    match = re.fullmatch(r"\s*(\d{2})/(\d{2})/(\d{2}|\d{4})\s*", text or "")
    if not match:
        return ""
    day, month, year = match.groups()
    if len(year) == 2:
        # The data starts in 1993, so a two-digit year below 93 is 2000s.
        year = f"19{year}" if int(year) >= 93 else f"20{year}"
    return f"{year}-{month}-{day}"


def parse_time(text: str) -> str:
    """Kick-off time as HH:MM, or "" when the column is absent or empty."""
    match = re.fullmatch(r"\s*(\d{1,2}):(\d{2})\s*", text or "")
    return f"{int(match.group(1)):02d}:{match.group(2)}" if match else ""


def _int(value: str) -> str:
    value = (value or "").strip()
    return value if value.isdigit() else ""


def enrichment_for(record: dict[str, str], our_name: str) -> dict[str, str] | None:
    """What this record can add, plus the date and side it applies to.

    Returns None when the record does not involve our club, or has no date.
    """
    home, away = record.get("HomeTeam", ""), record.get("AwayTeam", "")
    if our_name not in (home, away):
        return None
    date = parse_date(record.get("Date", ""))
    if not date:
        return None

    values = {column: _int(record.get(key, ""))
              for key, column in _ENRICHMENT.items()}
    values = {name: value for name, value in values.items() if value != ""}

    kickoff = parse_time(record.get("Time", ""))
    if kickoff:
        values["kickoff"] = kickoff

    return {"date": date, "we_are_home": home == our_name, "values": values,
            "home": home, "away": away,
            "ft_home": _int(record.get("FTHG", "")),
            "ft_away": _int(record.get("FTAG", "")),
            "division": record.get("Div", "")}


def apply_to(
    matches: list[dict[str, str]],
    enrichments: Iterable[dict],
    our_slug: str,
) -> tuple[int, list[str]]:
    """Fill blank fields on matching rows. Returns (enriched, unplaced dates).

    Only blank fields are filled: a value already present — from the primary
    source or from a hand correction — is never overwritten, because this
    source is the less authoritative of the two on anything they both carry.
    """
    by_date: dict[tuple[str, bool], dict[str, str]] = {}
    for row in matches:
        if row["home_club"] == our_slug:
            by_date[(row["date"], True)] = row
        elif row["away_club"] == our_slug:
            by_date[(row["date"], False)] = row

    enriched = 0
    unplaced: list[str] = []

    for item in enrichments:
        row = by_date.get((item["date"], item["we_are_home"]))
        if row is None:
            unplaced.append(item["date"])
            continue
        changed = False
        for name, value in item["values"].items():
            if row.get(name, "") == "":
                row[name] = value
                changed = True
        if changed:
            enriched += 1
            if SOURCE not in row["source"]:
                row["source"] = f"{row['source']}+{SOURCE}"

    return enriched, sorted(set(unplaced))



def find_our_name(
    records: Iterable[Mapping[str, str]],
    matches: Iterable[Mapping[str, str]],
    club: str,
    minimum: int = 20,
    margin: int = 5,
) -> str:
    """Which name this source uses for our club.

    Decided by evidence, not by spelling. Comparing names fails badly here:
    this source writes "West Brom", "Nott'm Forest", "Wolves" and "QPR",
    which share few or no words with the full names — and worse, a single
    shared word matches the wrong club ("West Bromwich Albion" and "West
    Ham", "Nottingham Forest" and "Forest Green").

    Instead each candidate is scored by how many of its fixtures match one we
    already hold — same date, same side, same score.

    The winner must also beat the runner-up by `margin`. An absolute floor is
    not enough: measured against the real cache, the correct name for
    Brighton scores 1,446 while unrelated clubs reach 50 purely by
    coincidence, so any fixed threshold near that noise would accept a wrong
    club. The true name wins by roughly thirty times; a club absent from this
    source has no such gap, and nothing is returned — importing another
    club's matches is far worse than importing none.
    """
    # The scoreline is part of the fingerprint, not just the date: clubs play
    # on the same Saturdays, so date and side alone would let any club that
    # was also at home that day score just as highly.
    ours: set[tuple[str, bool, str, str]] = set()
    for row in matches:
        if row.get("home_club") == club:
            ours.add((row["date"], True, row.get("ft_home", ""),
                      row.get("ft_away", "")))
        elif row.get("away_club") == club:
            ours.add((row["date"], False, row.get("ft_home", ""),
                      row.get("ft_away", "")))

    if not ours:
        return ""

    scores: dict[str, int] = {}
    for record in records:
        date = parse_date(record.get("Date", ""))
        if not date:
            continue
        home_goals = _int(record.get("FTHG", ""))
        away_goals = _int(record.get("FTAG", ""))
        home = (record.get("HomeTeam") or "").strip()
        away = (record.get("AwayTeam") or "").strip()
        if home and (date, True, home_goals, away_goals) in ours:
            scores[home] = scores.get(home, 0) + 1
        if away and (date, False, home_goals, away_goals) in ours:
            scores[away] = scores.get(away, 0) + 1

    if not scores:
        return ""
    ranked = sorted(scores.items(), key=lambda item: (-item[1], item[0]))
    best, top = ranked[0]
    if top < minimum:
        return ""
    runner_up = ranked[1][1] if len(ranked) > 1 else 0
    return best if top >= max(minimum, margin * runner_up) else ""



def learn_aliases(
    matches: list[dict[str, str]],
    items: Iterable[dict],
    our_slug: str,
) -> dict[str, str]:
    """Learn this source's club names from matches both sources agree on.

    Guessing that "Man United" means `manchester-united` is how a database
    quietly acquires two of every club. Instead, every fixture present in both
    sources pins one name to one slug: same date, same side, so the opponent
    is not in doubt. The mapping is evidence, not inference.
    """
    by_key = {}
    for row in matches:
        if row["home_club"] == our_slug:
            by_key[(row["date"], True)] = row["away_club"]
        elif row["away_club"] == our_slug:
            by_key[(row["date"], False)] = row["home_club"]

    aliases: dict[str, str] = {}
    for item in items:
        slug = by_key.get((item["date"], item["we_are_home"]))
        if slug is None:
            continue
        name = item["away"] if item["we_are_home"] else item["home"]
        aliases[name] = slug
    return aliases



def to_match(item: dict, aliases: dict[str, str], season: str) -> dict[str, str]:
    """Build a full match row. Only for seasons the primary source lacks.

    Raises rather than guessing if a club name has not been pinned by
    `learn_aliases`, and if the score is missing — a fixture with no result is
    one that has not been played.
    """
    from football.parse.base import blank_row
    from football.ids import match_id
    from football.schema import MATCHES

    home_slug = aliases.get(item["home"])
    away_slug = aliases.get(item["away"])
    if home_slug is None or away_slug is None:
        missing = item["home"] if home_slug is None else item["away"]
        raise KeyError(f"club name {missing!r} has not been pinned to a slug")
    if item["ft_home"] == "" or item["ft_away"] == "":
        raise ValueError(f"{item['date']}: no score, so no match was played")

    row = blank_row(MATCHES)
    row.update({
        "match_id": match_id(item["date"], home_slug, away_slug),
        "date": item["date"],
        "season": season,
        "home_club": home_slug,
        "away_club": away_slug,
        "competition": COMPETITIONS[item["division"]],
        "tier": TIERS[item["division"]],
        "ft_home": item["ft_home"],
        "ft_away": item["ft_away"],
        "status": "played",
        "source": SOURCE,
    })
    row.update(item["values"])
    return row
