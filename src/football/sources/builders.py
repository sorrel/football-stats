"""Turning each source's cached pages into rows.

One builder per source. Each reads only from the page cache, so a builder can
be re-run after a schema change without touching the network — which is the
whole reason the cache exists.

A builder never writes: it returns a `Batch`, and `sources.batch.apply`
decides what happens to it.
"""

from __future__ import annotations

import csv
import io
import json
from urllib.parse import quote
from collections.abc import Iterable

from football.cache import PageCache
from football.ids import slugify
from football.parse.base import blank_row
from football.schema import COMPETITIONS
from football.sources import engsoccer, footballdata, openfootball
from football.sources import openfootball_import as of_import
from football.sources import standings as fj_standings
from football.sources.standings import season_id
from football.sources import wikipedia
from football.sources.batch import Batch
from football.sources.common import season_label
from football.sources.registry import (
    ENGSOCCER, FJELSTUL, FOOTBALL_DATA, OPENFOOTBALL, WIKIPEDIA_API,
    Source, register)

#: The seasons each source is asked for. Wide enough to cover any English
#: club; a season with no article or no file is simply skipped.
_SEASONS = range(1993, 2027)


def _rows(cache: PageCache, url: str) -> list[dict[str, str]]:
    """Read a cached CSV. Missing means the crawl has not reached it yet."""
    if not cache.has(url):
        return []
    return list(csv.DictReader(io.StringIO(cache.get(url))))


# --------------------------------------------------------------------------
# engsoccerdata — league, FA Cup, League Cup and play-offs
# --------------------------------------------------------------------------

_ENGSOCCER_FILES = ("england", "facup", "leaguecup", "englandplayoffs")


def engsoccer_keys(context: dict) -> list[str]:
    return [f"{ENGSOCCER}/{name}.csv" for name in _ENGSOCCER_FILES]


def build_engsoccer(cache: PageCache, club: str, context: dict) -> Batch:
    league = _rows(cache, f"{ENGSOCCER}/england.csv")
    cup = _rows(cache, f"{ENGSOCCER}/facup.csv")
    league_cup = _rows(cache, f"{ENGSOCCER}/leaguecup.csv")
    playoffs = _rows(cache, f"{ENGSOCCER}/englandplayoffs.csv")

    # The club's name is taken from the file rather than from the database,
    # so a club we do not hold yet can still be imported — otherwise nothing
    # could ever be imported into an empty database.
    name = _name_in_source(league + cup + league_cup + playoffs, club)
    if not name:
        return Batch(notes=[f"no club in the cached files slugs to {club!r}"])

    ours = lambda records: [r for r in records
                            if name in (r.get("home"), r.get("visitor"))]
    league_ours = ours(league)
    cup_ours = [r for r in ours(cup) if engsoccer.is_real_match(r)]
    lc_ours = [r for r in ours(league_cup) if engsoccer.is_real_match(r)]
    po_ours = ours(playoffs)

    matches = [engsoccer.league_match(r) for r in league_ours]
    matches += [engsoccer.facup_match(r) for r in cup_ours]
    matches += [engsoccer.leaguecup_match(r) for r in lc_ours]
    matches += [engsoccer.playoff_match(r) for r in po_ours]
    engsoccer.link_replays(matches)

    names: dict[str, str] = {}
    for record in league_ours + cup_ours + lc_ours + po_ours:
        for display in (record["home"], record["visitor"]):
            names.setdefault(slugify(display), display)

    league_clubs = engsoccer.league_club_slugs(league) if league else None
    competitions = engsoccer.competitions_from(matches)
    for competition in competitions:
        competition["type"] = engsoccer.competition_type(competition["slug"])
        if competition["slug"] == "league-cup":
            competition["name"] = "League Cup"

    return Batch(
        matches=matches,
        clubs=engsoccer.clubs_from(matches, names, league_clubs),
        competitions=competitions,
        venues=engsoccer.venues_from(cup_ours + lc_ours + po_ours),
        notes=[] if league else ["england.csv not cached yet"],
    )


# --------------------------------------------------------------------------
# football-data.co.uk — half-time scores, cards and kick-off times from 1993
# --------------------------------------------------------------------------


def footballdata_keys(context: dict) -> list[str]:
    return [url for year in _SEASONS
            for url in footballdata.season_urls(year, FOOTBALL_DATA)]


def _name_in_source(records: list[dict[str, str]], club: str) -> str:
    """The name these files use for `club`, found by slug."""
    for record in records:
        for side in ("home", "visitor"):
            value = record.get(side) or ""
            if value and slugify(value) == club:
                return value
    return ""


def build_footballdata(cache: PageCache, club: str, context: dict) -> Batch:
    by_year: dict[int, list[dict[str, str]]] = {}
    for year in _SEASONS:
        for url in footballdata.season_urls(year, FOOTBALL_DATA):
            if not cache.has(url):
                continue
            by_year.setdefault(year, []).extend(
                footballdata.records(cache.get(url)))

    # This source names clubs its own way ("West Brom", "QPR"), so which
    # name is ours is decided by which one's fixtures line up with matches we
    # already hold — never by comparing spellings.
    all_records = [record for records in by_year.values() for record in records]
    short = footballdata.find_our_name(all_records, context["matches"], club)
    if not short:
        return Batch(notes=[
            "could not identify this club in the cached files; import "
            "engsoccerdata first so there are fixtures to match against"])

    items_by_season: dict[str, list[dict]] = {}
    for year, records in by_year.items():
        for record in records:
            item = footballdata.enrichment_for(record, short)
            if item:
                items_by_season.setdefault(season_label(year), []).append(item)

    items = [i for season in items_by_season.values() for i in season]
    if not items:
        return Batch(notes=[f"no records for {short!r} in the cached files"])

    # Copied, not aliased: these rows are enriched in place below, and
    # another builder must not see half-applied changes.
    existing = [dict(row) for row in context["matches"]]
    aliases = footballdata.learn_aliases(existing, items, club)
    aliases[short] = club

    # This club's seasons, not the store's: another club covering a season
    # says nothing about whether ours has matches in it.
    have = {row["season"] for row in existing
            if club in (row["home_club"], row["away_club"])}
    built: list[dict[str, str]] = []
    notes: list[str] = []
    for season, season_items in sorted(items_by_season.items()):
        if season in have:
            continue
        for item in season_items:
            try:
                built.append(footballdata.to_match(item, aliases, season))
            except (KeyError, ValueError) as exc:
                notes.append(f"{season}: {exc}")

    enriched, unplaced = footballdata.apply_to(existing, items, club)
    changed = [row for row in existing if footballdata.SOURCE in row["source"]]
    if unplaced:
        notes.append(f"{len(unplaced)} records could not be placed")

    return Batch(matches=built + changed, notes=notes)


# --------------------------------------------------------------------------
# openfootball — cups from 2018-19, and Europe
# --------------------------------------------------------------------------

_OF_CUPS = ("eflcup", "facup")


def openfootball_keys(context: dict) -> list[str]:
    keys = [f"{OPENFOOTBALL}/england/master/{season_label(y)}/{f}.txt"
            for y in range(2000, 2026) for f in _OF_CUPS]
    keys += [f"{OPENFOOTBALL}/champions-league/master/{season_label(y)}/{f}.txt"
             for y in range(2011, 2026) for f in ("el", "cl", "conf")]
    return keys


def build_openfootball(cache: PageCache, club: str, context: dict) -> Batch:
    known = {row["slug"] for row in context["clubs"]}
    matches: list[dict[str, str]] = []
    notes: list[str] = []

    for url in openfootball_keys(context):
        if not cache.has(url):
            continue
        text = cache.get(url)
        if not text.strip() or text.lstrip().startswith("404"):
            continue
        document = openfootball.parse(text)
        rows, unresolved = of_import.convert(
            document.fixtures, document.season, document.competition,
            known, club)
        matches += rows
        notes += [f"{document.season}: unresolved club {name!r}"
                  for name in unresolved]

    # The competitions these matches name must exist, or the rebuild refuses.
    # Brighton only reached the Europa League, which another source had
    # already created; Arsenal's Champions League ties had nothing to point at.
    competitions = []
    for slug in sorted({row["competition"] for row in matches}):
        competition = blank_row(COMPETITIONS)
        competition.update({
            "slug": slug,
            "name": engsoccer.competition_name(slug),
            "type": engsoccer.competition_type(slug),
        })
        competitions.append(competition)

    return Batch(matches=matches, competitions=competitions, notes=notes)


# --------------------------------------------------------------------------
# Fjelstul standings — final league positions to 2023-24
# --------------------------------------------------------------------------


def standings_keys(context: dict) -> list[str]:
    return [f"{FJELSTUL}/standings.csv"]


def build_standings(cache: PageCache, club: str, context: dict) -> Batch:
    url = f"{FJELSTUL}/standings.csv"
    records = _rows(cache, url)
    if not records:
        return Batch(notes=["standings.csv not cached yet"])
    seasons, skipped = fj_standings.convert(
        records, context["club_names"], club, context["league_seasons"])
    notes = [f"{len(skipped)} seasons had no matches to place them against"] \
        if skipped else []
    return Batch(seasons=seasons, notes=notes)


# --------------------------------------------------------------------------
# Wikipedia — league tables from 2024-25, and attendances
# --------------------------------------------------------------------------


#: A competition's Wikipedia season-article title. The tier is not enough:
#: the article for the second tier is "EFL Championship", not "Tier 2".
_WIKI_COMPETITIONS = {
    "premier-league": "Premier_League",
    "championship": "EFL_Championship",
    "league-one": "EFL_League_One",
    "league-two": "EFL_League_Two",
}

#: The seasons the standings source does not reach.
_WIKI_TABLE_YEARS = range(2024, 2027)


def wikipedia_table_keys(context: dict) -> list[str]:
    """The season articles for the divisions this club actually played in.

    Fetching the Premier League regardless of club looked right while only
    Brighton was loaded, and quietly returned nothing for anyone below it.
    The club's own most recent division is what says which article to read;
    a club that has since been promoted or relegated gets both.
    """
    seasons = context.get("league_seasons") or {}
    recent = {competition for season, (competition, _) in seasons.items()
              if season >= "2020-21"}
    articles = {_WIKI_COMPETITIONS[slug] for slug in recent
                if slug in _WIKI_COMPETITIONS}
    if not articles:
        # Nothing recent to go on: the top flight is the likeliest, and a
        # page with no row for this club simply yields nothing.
        articles = {"Premier_League"}

    return [f"{WIKIPEDIA_API}{_wiki_season(y)}_{article}"
            for y in _WIKI_TABLE_YEARS for article in sorted(articles)]


def _wiki_season(start: int) -> str:
    return f"{start}%E2%80%93{(start + 1) % 100:02d}"


def build_wikipedia_tables(cache: PageCache, club: str, context: dict) -> Batch:
    seasons: list[dict[str, str]] = []
    notes: list[str] = []
    known = context["league_seasons"]
    seen: set[str] = set()

    # The same keys the fetcher used, so the builder cannot read a different
    # division from the one that was downloaded.
    for url in wikipedia_table_keys(context):
        if not cache.has(url):
            continue
        year = int(url.rsplit("=", 1)[-1][:4])
        page = json.loads(cache.get(url))
        if "error" in page:
            continue
        text = page["parse"]["wikitext"]["*"]
        season = season_label(year)
        if not wikipedia.is_complete(text):
            notes.append(f"{season} is not complete, so has no final position")
            continue
        rows = [r for r in wikipedia.parse_league_table(text)
                if slugify(r.name) == club]
        if not rows:
            continue
        competition, tier = known.get(season, ("premier-league", "1"))
        if season_id(season, club, competition) in seen:
            continue
        seen.add(season_id(season, club, competition))
        row = {name: "" for name in _seasons_fields()}
        row.update({
            "season_id": season_id(season, club, competition),
            "club": club, "season": season, "competition": competition,
            "tier": tier, "position": str(rows[0].position),
            "points": str(rows[0].points(year)),
            "point_adjustment": (str(rows[0].point_adjustment)
                                 if rows[0].point_adjustment else ""),
            "source": "wikipedia"})
        seasons.append(row)

    return Batch(seasons=seasons, notes=notes)


def _seasons_fields() -> Iterable[str]:
    from football.schema import SEASONS
    return SEASONS.field_names()


#: Clubs style themselves F.C. or A.F.C., and Wikipedia titles follow.
#: Which one cannot be told from the name — Barrow are Barrow A.F.C. — so
#: both are offered and whichever exists is the one that parses.
_CLUB_SUFFIXES = ("F.C.", "A.F.C.")


def wikipedia_article_titles(club_name: str) -> list[str]:
    """The club's possible article titles, URL-encoded.

    Built from the display name rather than the slug: the article is
    "Brighton & Hove Albion F.C. season", and no slug carries the ampersand
    or the suffix.
    """
    if club_name.endswith(("F.C.", "A.F.C.", "FC", "AFC")):
        names = [club_name]
    elif club_name.startswith(("AFC ", "A.F.C. ")):
        # Already carries it at the front: AFC Bournemouth, AFC Wimbledon.
        names = [club_name]
    else:
        names = [f"{club_name} {suffix}" for suffix in _CLUB_SUFFIXES]
    return [quote(name.replace(" ", "_"), safe="_") for name in names]


def wikipedia_attendance_keys(context: dict) -> list[str]:
    titles = wikipedia_article_titles(context["club_name"])
    return [f"{WIKIPEDIA_API}{_wiki_season(y)}_{title}_season"
            for y in range(1995, 2027) for title in titles]


def build_wikipedia_attendance(cache: PageCache, club: str, context: dict) -> Batch:
    boxes = []
    for url in wikipedia_attendance_keys(context):
        if not cache.has(url):
            continue
        page = json.loads(cache.get(url))
        if "error" in page:
            continue
        boxes += wikipedia.parse_match_boxes(page["parse"]["wikitext"]["*"])

    if not boxes:
        return Batch(notes=["no season articles cached yet"])

    # Copied, not aliased: these rows are enriched in place below, and
    # another builder must not see half-applied changes.
    existing = [dict(row) for row in context["matches"]]
    filled, unmatched = wikipedia.enrich_matches(existing, boxes, club, slugify)
    changed = [row for row in existing if "wikipedia" in row["source"]]
    notes = [f"{len(unmatched)} boxes matched nothing (friendlies and the like)"] \
        if unmatched else []
    return Batch(matches=changed, notes=notes)


def register_all() -> None:
    """Declare every source. Called once, at import time."""
    register(Source(
        name="engsoccerdata", covers="League, FA Cup, League Cup, play-offs",
        licence="Free, non-commercial",
        keys=engsoccer_keys, build=build_engsoccer))
    register(Source(
        name="football-data", covers="Half-time scores, cards, kick-offs (1993 on)",
        licence="Free", keys=footballdata_keys, build=build_footballdata))
    register(Source(
        name="openfootball", covers="Cups (2018-19 on) and Europe",
        licence="CC0 (public domain)",
        keys=openfootball_keys, build=build_openfootball))
    register(Source(
        name="standings", covers="Final league positions to 2023-24",
        licence="CC-BY-SA 4.0", keys=standings_keys, build=build_standings))
    register(Source(
        name="wikipedia-tables", covers="League tables from 2024-25",
        licence="CC-BY-SA 4.0",
        keys=wikipedia_table_keys, build=build_wikipedia_tables))
    register(Source(
        name="wikipedia-attendance", covers="Attendances (roughly 2009 on)",
        licence="CC-BY-SA 4.0",
        keys=wikipedia_attendance_keys, build=build_wikipedia_attendance))
    register(Source(
        name="11v11", covers="Cards before 1993, attendances before 2009",
        licence="Unclear; likely licensed",
        keys=lambda club: [], build=lambda cache, club, context: Batch(),
        available=False,
        unavailable_because=(
            "behind a bot challenge, and the data may be licensed — "
            "no automated access has been agreed")))


register_all()
