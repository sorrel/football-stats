"""Seasons the record does not fully hold, and what runs may do across them.

The bug this guards against: Brighton's record before 1920-21 holds only FA
Cup ties, so four home ties spread over five Southern League seasons read as
four consecutive home matches without a goal — a run of 4 lasting 2,195 days,
which is not a fact about the club but a fact about the record.
"""

import sqlite3

from click.testing import CliRunner

from football import db, schema, store
from football.analysis import coverage, runs
from football.analysis.filters import Filters
from football.cli import cli
from football.parse.base import blank_row

CLUB = "brighton-hove-albion"


def _m(date, opponent, gf, ga, season, competition="division-one", home=True):
    row = blank_row(schema.MATCHES)
    row.update({
        "match_id": f"{date}_{CLUB if home else opponent}_"
                    f"{opponent if home else CLUB}",
        "date": date, "season": season,
        "home_club": CLUB if home else opponent,
        "away_club": opponent if home else CLUB,
        "competition": competition, "status": "played", "source": "test",
        "tier": "1" if competition == "division-one" else "",
        "ft_home": str(gf if home else ga), "ft_away": str(ga if home else gf),
    })
    return row


#: The shape that produced the wrong answer, in miniature: cup-only seasons
#: in which the club failed to score at home, then a season the record holds
#: in full. Nothing here says the two cup ties were consecutive matches.
CUP_ONLY_THEN_LEAGUE = [
    _m("1908-02-05", "liverpool", 0, 1, "1907-08", competition="fa-cup"),
    _m("1909-01-16", "sunderland", 2, 1, "1908-09", competition="fa-cup",
       home=False),
    _m("1910-01-15", "southampton", 0, 2, "1909-10", competition="fa-cup"),
    _m("1911-02-04", "coventry-city", 0, 1, "1910-11", competition="fa-cup"),
    _m("1921-09-10", "arsenal", 1, 0, "1921-22"),
    _m("1921-09-17", "watford", 0, 1, "1921-22"),
    _m("1921-09-24", "everton", 0, 2, "1921-22"),
    _m("1921-10-01", "chelsea", 2, 0, "1921-22"),
]


def _seed(data_dir, matches):
    clubs = {s for m in matches for s in (m["home_club"], m["away_club"])}
    store.write_table(data_dir, schema.CLUBS, [
        {"slug": s, "name": s, "former_names": "", "english_league": "true",
         "country": "England", "imported": "true"} for s in sorted(clubs)])
    store.write_table(data_dir, schema.COMPETITIONS, [
        {"slug": "division-one", "name": "Division One", "type": "league",
         "tier": "1", "first_season": "", "last_season": ""},
        {"slug": "fa-cup", "name": "FA Cup", "type": "fa-cup",
         "tier": "", "first_season": "", "last_season": ""}])
    store.write_table(data_dir, schema.VENUES, [])
    store.write_matches(data_dir, matches)


def _build(tmp_path, matches=CUP_ONLY_THEN_LEAGUE) -> sqlite3.Connection:
    _seed(tmp_path, matches)
    return db.build(tmp_path, tmp_path / "f.db")


# --- what counts as a season the record does not hold ----------------------

def test_a_season_with_no_league_matches_is_incomplete(tmp_path):
    """A club playing cup ties was in a league that season, whatever the
    record holds. Its absence is a gap in the record, not a quiet year."""
    conn = _build(tmp_path)
    assert coverage.incomplete_seasons(conn, CLUB) == frozenset(
        {"1907-08", "1908-09", "1909-10", "1910-11"})


def test_a_season_with_league_matches_is_complete(tmp_path):
    conn = _build(tmp_path)
    assert "1921-22" not in coverage.incomplete_seasons(conn, CLUB)


def test_a_question_about_one_competition_judges_that_competition(tmp_path):
    """"The longest run of FA Cup ties without a goal" is a fair question of
    a record that holds the FA Cup in full, whatever else is missing."""
    conn = _build(tmp_path)
    assert coverage.incomplete_seasons(conn, CLUB, competition="fa-cup") == frozenset()


def test_stretches_reads_consecutive_seasons_as_a_range(tmp_path):
    assert coverage.stretches({"1907-08", "1908-09", "1909-10", "1945-46"}) == [
        "1907-08 to 1909-10", "1945-46"]


# --- what runs may do across them ------------------------------------------

def test_a_run_does_not_cross_a_season_the_record_does_not_hold(tmp_path):
    """The three cup ties are the whole of three seasons we hold in part.
    Calling them a run of 3 asserts the club played nothing in between."""
    conn = _build(tmp_path)
    matches = runs.matches_in_order(conn, Filters(club=CLUB, side="home"))
    assert runs.longest(matches, "without-scoring").length == 2, (
        "only the two 1921-22 home matches are known to be consecutive")


def test_the_same_run_is_a_fact_within_one_competition(tmp_path):
    conn = _build(tmp_path)
    matches = runs.matches_in_order(
        conn, Filters(club=CLUB, side="home", competition="fa-cup"))
    assert runs.longest(matches, "without-scoring").length == 3


def test_a_run_reaching_a_gap_is_only_a_lower_bound(tmp_path):
    """The run ends where the record does. How long the drought really ran
    is unknown, so its days are at least that many, not exactly."""
    conn = _build(tmp_path, [
        _m("1908-02-05", "liverpool", 0, 1, "1907-08", competition="fa-cup"),
        _m("1921-09-10", "arsenal", 1, 0, "1921-22"),
        _m("1921-09-17", "watford", 0, 1, "1921-22"),
        _m("1921-09-24", "everton", 0, 2, "1921-22"),
    ])
    run = runs.longest(runs.matches_in_order(conn, Filters(club=CLUB)),
                       "without-scoring")
    assert run.length == 2 and not run.bounded


def test_a_match_built_by_hand_follows_the_one_before_it():
    """Adjacency is decided where the matches are read, so everything else
    that builds a Match keeps working."""
    match = runs.Match("1982-08-28", "1982-83", "division-one", "arsenal",
                       "H", 1, 0, "W")
    assert match.follows


# --- seasons the record skips entirely -------------------------------------

#: Barrow's shape: a Football League record, then nothing at all while they
#: played non-League football, then the League again.
LEAGUE_THEN_NOTHING = [
    _m("1971-04-24", "chester", 0, 1, "1970-71"),
    _m("1972-04-22", "crewe-alexandra", 0, 2, "1971-72"),
    _m("2016-08-13", "gateshead", 0, 1, "2016-17"),
    _m("2020-09-12", "stevenage", 0, 0, "2020-21"),
    _m("2020-09-19", "carlisle-united", 1, 0, "2020-21"),
]


def test_a_season_the_record_skips_entirely_is_a_gap(tmp_path):
    """No cup tie gives this one away: the seasons are simply not there."""
    conn = _build(tmp_path, LEAGUE_THEN_NOTHING)
    assert "1972-73" in coverage.absent_seasons(conn, CLUB)
    assert "1970-71" not in coverage.absent_seasons(conn, CLUB)


def test_a_run_does_not_cross_the_seasons_the_record_skips(tmp_path):
    """Four defeats without a goal, spread over fifty years and two eras of
    football nobody imported, are not a run of four."""
    conn = _build(tmp_path, LEAGUE_THEN_NOTHING)
    run = runs.longest(runs.matches_in_order(conn, Filters(club=CLUB)),
                       "without-scoring")
    assert run.length == 2, "only the consecutive 1970-71 and 1971-72 matches"
    assert not run.bounded, "the record cannot see how the drought ended"


# --- saying so -------------------------------------------------------------

def _args(tmp_path):
    return ["--data-dir", str(tmp_path / "data"), "--db", str(tmp_path / "f.db")]


def _invoke(tmp_path, *command):
    _seed(tmp_path / "data", CUP_ONLY_THEN_LEAGUE)
    runner = CliRunner()
    runner.invoke(cli, [*_args(tmp_path), "rebuild"])
    result = runner.invoke(cli, [*_args(tmp_path), *command, "--club", CLUB])
    assert result.exit_code == 0, result.output
    return result.output


def test_the_coverage_command_names_the_seasons_the_record_lacks(tmp_path):
    output = _invoke(tmp_path, "coverage")
    assert "1907-08 to 1910-11" in output


def test_the_coverage_command_says_so_when_nothing_is_missing(tmp_path):
    _seed(tmp_path / "data", CUP_ONLY_THEN_LEAGUE[-4:])
    runner = CliRunner()
    runner.invoke(cli, [*_args(tmp_path), "rebuild"])
    result = runner.invoke(cli, [*_args(tmp_path), "coverage", "--club", CLUB])
    assert result.exit_code == 0, result.output
    assert "every season" in result.output.lower()


def test_the_runs_command_reports_the_gap_it_did_not_cross(tmp_path):
    output = _invoke(tmp_path, "runs")
    assert "1907-08 to 1910-11" in output


def test_the_coverage_command_names_the_seasons_held_at_all(tmp_path):
    _seed(tmp_path / "data", LEAGUE_THEN_NOTHING)
    runner = CliRunner()
    runner.invoke(cli, [*_args(tmp_path), "rebuild"])
    result = runner.invoke(cli, [*_args(tmp_path), "coverage", "--club", CLUB])
    assert result.exit_code == 0, result.output
    assert "1972-73 to 2015-16" in result.output


# --- the timeline, and what "held in full" means ----------------------------

#: A season either side of the First World War, and nothing recorded for
#: any season in between — which the war years alone can explain.
WAR_GAP = [
    _m("1913-08-30", "chelsea", 1, 0, "1913-14"),
    _m("1920-09-04", "fulham", 2, 1, "1920-21"),
]

#: The club's last recorded season is cup football only — the league has
#: not yet resumed, so nothing after it can be called held in full.
ENDS_IN_CUP_ONLY = [
    _m("1921-09-10", "arsenal", 1, 0, "1921-22"),
    _m("1922-01-14", "fulham", 2, 0, "1922-23", competition="fa-cup"),
]


def test_timeline_marks_a_season_the_record_skips_entirely_absent(tmp_path):
    conn = _build(tmp_path, LEAGUE_THEN_NOTHING)
    line = dict(coverage.timeline(conn, CLUB))
    assert line["1970-71"] == "held"
    assert line["1972-73"] == "absent"
    assert line["2016-17"] == "held"


def test_timeline_marks_a_cup_only_season_partial(tmp_path):
    conn = _build(tmp_path)
    line = dict(coverage.timeline(conn, CLUB))
    assert line["1907-08"] == "partial"
    assert line["1921-22"] == "held"


def test_timeline_marks_the_war_years_war_not_absent(tmp_path):
    """1914-15 is a genuine gap — the League completed that season before
    suspending — so only 1915-16 to 1919-20 is war."""
    conn = _build(tmp_path, WAR_GAP)
    line = dict(coverage.timeline(conn, CLUB))
    assert line["1914-15"] == "absent"
    assert line["1915-16"] == "war"
    assert line["1919-20"] == "war"


def test_held_in_full_from_the_season_after_the_last_gap(tmp_path):
    """2016-17 is an isolated held season with more absence either side of
    it, so the clean run only really starts at 2020-21."""
    conn = _build(tmp_path, LEAGUE_THEN_NOTHING)
    assert coverage.held_in_full_from(conn, CLUB) == "2020-21"


def test_held_in_full_from_treats_a_war_as_no_gap_at_all(tmp_path):
    """Nothing is missing across a war — there was nothing to hold — so it
    does not break the trailing run the way a real gap would."""
    conn = _build(tmp_path, WAR_GAP)
    assert coverage.held_in_full_from(conn, CLUB) == "1915-16"


def test_held_in_full_from_is_none_when_the_last_season_is_only_partly_held(tmp_path):
    conn = _build(tmp_path, ENDS_IN_CUP_ONLY)
    assert coverage.held_in_full_from(conn, CLUB) is None


# --- the coverage command's fuller picture ----------------------------------

def _invoke_with(tmp_path, matches, *command):
    _seed(tmp_path / "data", matches)
    runner = CliRunner()
    runner.invoke(cli, [*_args(tmp_path), "rebuild"])
    result = runner.invoke(cli, [*_args(tmp_path), *command, "--club", CLUB])
    assert result.exit_code == 0, result.output
    return result.output


def test_the_coverage_command_tells_war_apart_from_a_real_gap(tmp_path):
    """1914-15 is a genuine gap — the League played it out before
    suspending — so it is "nothing at all" while 1915-16 to 1919-20, the
    war proper, is told apart as "war"."""
    output = _invoke_with(tmp_path, WAR_GAP, "coverage")
    assert "1915-16 to 1919-20 | war" in output
    assert "1914-15            | nothing at all" in output
    assert "no football was played" in output.lower()


def test_the_coverage_command_says_what_is_held_in_full(tmp_path):
    output = _invoke_with(tmp_path, LEAGUE_THEN_NOTHING, "coverage")
    assert "Held in full from 2020-21 onwards" in output


def test_the_coverage_command_says_nothing_is_held_in_full_mid_gap(tmp_path):
    """The record's own last season is cup football only, so nothing after
    it can honestly be called a clean run."""
    output = _invoke_with(tmp_path, ENDS_IN_CUP_ONLY, "coverage")
    assert "Held in full" not in output


def test_the_coverage_command_shows_a_season_by_season_strip(tmp_path):
    output = _invoke_with(tmp_path, LEAGUE_THEN_NOTHING, "coverage")
    assert "held in full" in output
    assert "not held" in output
    assert "1970-71" in output and "2020-21" in output


def test_the_coverage_command_reports_recorded_figures(tmp_path):
    output = _invoke_with(tmp_path, CUP_ONLY_THEN_LEAGUE, "coverage")
    assert "Recorded figures" in output
    assert "crowd" in output and "scores" in output and "cards" in output
    assert "1976-77" in output
