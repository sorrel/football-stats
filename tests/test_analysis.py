"""Records, runs and extremes, against a small hand-built database."""

import sqlite3

import pytest

from football import db, schema, store
from football.analysis import extremes as ex
from football.analysis import records, runs
from football.analysis.filters import Filters
from football.parse.base import blank_row

CLUB = "brighton-hove-albion"


def _seed(tmp_path, matches):
    clubs = {s for m in matches for s in (m["home_club"], m["away_club"])}
    store.write_table(tmp_path, schema.CLUBS, [
        {"slug": s, "name": s, "former_names": "",
         "english_league": "false" if s == "wisbech-town" else "true",
         "country": "England"} for s in sorted(clubs)])
    store.write_table(tmp_path, schema.COMPETITIONS, [
        {"slug": "division-one", "name": "Division One", "type": "league",
         "tier": "1", "first_season": "", "last_season": ""},
        {"slug": "fa-cup", "name": "FA Cup", "type": "domestic-cup",
         "tier": "", "first_season": "", "last_season": ""}])
    store.write_table(tmp_path, schema.VENUES, [])
    store.write_matches(tmp_path, matches)
    return db.build(tmp_path, tmp_path / "f.db")


def _m(date, opponent, gf, ga, season="1982-83", competition="division-one",
       home=True, attendance="", tier="1", **extra):
    row = blank_row(schema.MATCHES)
    us, them = "brighton-hove-albion", opponent
    row.update({
        "match_id": f"{date}_{us if home else them}_{them if home else us}",
        "date": date, "season": season,
        "home_club": us if home else them, "away_club": them if home else us,
        "competition": competition, "status": "played", "source": "test",
        "ft_home": str(gf if home else ga), "ft_away": str(ga if home else gf),
        "attendance": attendance,
        "tier": tier if competition == "division-one" else "",
    })
    row.update(extra)
    return row


@pytest.fixture
def conn(tmp_path):
    return _seed(tmp_path, [
        _m("1982-08-28", "ipswich-town", 1, 1),
        _m("1982-09-04", "arsenal", 2, 0),
        _m("1982-09-11", "watford", 3, 0, home=False),
        _m("1982-09-18", "everton", 0, 3),
        _m("1982-10-02", "wisbech-town", 10, 1, competition="fa-cup",
           attendance="15000"),
        _m("1982-10-09", "arsenal", 1, 2, home=False, attendance="40000"),
    ])


def test_record_counts_results_and_goals(conn):
    r = records.record(conn, Filters(club=CLUB))
    assert (r.played, r.won, r.drawn, r.lost) == (6, 3, 1, 2)
    assert (r.goals_for, r.goals_against) == (17, 7)


def test_win_percentage_is_of_matches_played(conn):
    assert records.record(conn, Filters(club=CLUB)).win_percentage == pytest.approx(50.0)


def test_a_competition_filter_narrows_the_record(conn):
    r = records.record(conn, Filters(club=CLUB, competition="fa-cup"))
    assert (r.played, r.won) == (1, 1)


def test_a_tier_filter_uses_the_match_not_the_competition_name(conn):
    """Division One was tier 1 until 1992 and tier 2 after, so the name alone
    cannot say which tier a match was played at. The tier is on the match."""
    assert records.record(conn, Filters(club=CLUB, tier=1)).played == 5


def test_league_only_excludes_non_league_opposition(conn):
    r = records.record(conn, Filters(club=CLUB, english_league_only=True))
    assert r.played == 5, "the Wisbech Town cup tie must be excluded"


def test_home_and_away_split(conn):
    assert records.record(conn, Filters(club=CLUB, side="home")).played == 4
    assert records.record(conn, Filters(club=CLUB, side="away")).played == 2


def test_a_match_with_no_score_is_not_counted_as_nil_nil(tmp_path):
    conn = _seed(tmp_path, [_m("1982-08-28", "arsenal", 1, 0),
                            dict(_m("1982-09-04", "watford", 0, 0),
                                 ft_home="", ft_away="")])
    r = records.record(conn, Filters(club=CLUB))
    assert r.goals_for == 1, "the unknown match must not contribute goals"
    assert r.without_score == 1


def test_longest_unbeaten_run(conn):
    ms = runs.matches_in_order(conn, Filters(club=CLUB))
    run = runs.longest(ms, "unbeaten")
    assert run.length == 3  # draw, win, win before the Everton defeat
    assert run.start.date == "1982-08-28" and run.end.date == "1982-09-11"


def test_longest_winning_run(conn):
    ms = runs.matches_in_order(conn, Filters(club=CLUB))
    assert runs.longest(ms, "wins").length == 2


def test_a_run_is_broken_by_a_match_with_no_known_result(tmp_path):
    """An unbeaten run through an unknown result is an assumption, not a fact."""
    conn = _seed(tmp_path, [
        _m("1982-08-28", "arsenal", 1, 0),
        dict(_m("1982-09-04", "watford", 0, 0), ft_home="", ft_away=""),
        _m("1982-09-11", "everton", 2, 0),
    ])
    ms = runs.matches_in_order(conn, Filters(club=CLUB))
    assert runs.longest(ms, "wins").length == 1


def test_no_run_of_that_kind_returns_nothing(tmp_path):
    conn = _seed(tmp_path, [_m("1982-08-28", "arsenal", 1, 0)])
    ms = runs.matches_in_order(conn, Filters(club=CLUB))
    assert runs.longest(ms, "losses") is None


def test_all_runs_are_returned_longest_first(conn):
    ms = runs.matches_in_order(conn, Filters(club=CLUB))
    found = runs.all_runs(ms, "unbeaten", minimum=1)
    assert [r.length for r in found] == sorted([r.length for r in found], reverse=True)


def test_biggest_win_by_margin(conn):
    rows, _ = ex.extremes(conn, Filters(club=CLUB), by="margin", limit=1)
    assert rows[0][3] == "wisbech-town" and rows[0][5] == 10


def test_extremes_report_the_coverage_behind_them(conn):
    _, cover = ex.extremes(conn, Filters(club=CLUB), by="attendance")
    assert cover.available == 2 and cover.total == 6
    assert cover.is_partial
    assert "2 of 6" in cover.describe()


def test_attendance_extremes_ignore_matches_with_none_recorded(conn):
    rows, _ = ex.extremes(conn, Filters(club=CLUB), by="attendance", limit=10)
    assert len(rows) == 2, "only matches with a recorded crowd may be ranked"
    assert rows[0][7] == 40000


def test_a_run_without_scoring_counts_the_matches_that_drew_a_blank(tmp_path):
    conn = _seed(tmp_path, [
        _m("1982-08-28", "arsenal", 1, 0),
        _m("1982-09-04", "watford", 0, 1),
        _m("1982-09-11", "everton", 0, 0),
        _m("1982-09-18", "ipswich-town", 0, 2),
        _m("1982-09-25", "wisbech-town", 2, 0),
    ])
    ms = runs.matches_in_order(conn, Filters(club=CLUB))
    run = runs.longest(ms, "without-scoring")
    assert run.length == 3
    assert run.start.date == "1982-09-04" and run.end.date == "1982-09-18"


def test_a_goalless_draw_continues_both_a_clean_sheet_and_a_scoreless_run(tmp_path):
    conn = _seed(tmp_path, [_m("1982-08-28", "arsenal", 0, 0)])
    ms = runs.matches_in_order(conn, Filters(club=CLUB))
    assert runs.longest(ms, "clean-sheets").length == 1
    assert runs.longest(ms, "without-scoring").length == 1


def test_a_scoreless_run_is_broken_by_a_match_with_no_score(tmp_path):
    """Nobody knows whether they scored, so the run cannot be said to continue."""
    conn = _seed(tmp_path, [
        _m("1982-08-28", "arsenal", 0, 1),
        dict(_m("1982-09-04", "watford", 0, 0), ft_home="", ft_away=""),
        _m("1982-09-11", "everton", 0, 2),
    ])
    ms = runs.matches_in_order(conn, Filters(club=CLUB))
    assert runs.longest(ms, "without-scoring").length == 1


def test_a_run_knows_the_matches_that_bookended_it(conn):
    ms = runs.matches_in_order(conn, Filters(club=CLUB))
    run = runs.longest(ms, "wins")
    assert run.before.date == "1982-08-28", "the draw that preceded the two wins"
    assert run.after.date == "1982-09-18", "the Everton defeat that ended them"


def test_a_run_that_opens_the_record_has_nothing_before_it(conn):
    ms = runs.matches_in_order(conn, Filters(club=CLUB))
    assert runs.longest(ms, "unbeaten").before is None


def test_a_run_that_closes_the_record_has_nothing_after_it(tmp_path):
    conn = _seed(tmp_path, [
        _m("1982-08-28", "arsenal", 1, 0),
        _m("1982-09-04", "watford", 0, 1),
        _m("1982-09-11", "everton", 0, 2),
    ])
    ms = runs.matches_in_order(conn, Filters(club=CLUB))
    run = runs.longest(ms, "losses")
    assert run.length == 2 and run.after is None


def test_a_winless_gap_is_measured_from_the_last_win_to_the_next(tmp_path):
    conn = _seed(tmp_path, [
        _m("1982-01-01", "arsenal", 1, 0),
        _m("1982-01-08", "watford", 0, 1),
        _m("1982-01-15", "everton", 1, 1),
        _m("1982-01-31", "ipswich-town", 2, 0),
    ])
    ms = runs.matches_in_order(conn, Filters(club=CLUB))
    run = runs.longest(ms, "without-win")
    assert run.length == 2
    assert run.days == 30, "1 January to 31 January, win to win"
    assert run.bounded


def test_an_unfinished_gap_reports_the_span_it_can_prove(tmp_path):
    """A gap still running at the end of the record is a lower bound, not a fact."""
    conn = _seed(tmp_path, [
        _m("1982-01-01", "arsenal", 1, 0),
        _m("1982-01-08", "watford", 0, 1),
        _m("1982-01-15", "everton", 1, 1),
    ])
    ms = runs.matches_in_order(conn, Filters(club=CLUB))
    run = runs.longest(ms, "without-win")
    assert not run.bounded
    assert run.days == 7, "8 January to 15 January is all that can be shown"


def test_a_gap_ended_by_an_unknown_result_is_not_treated_as_ended_by_a_win(tmp_path):
    conn = _seed(tmp_path, [
        _m("1982-01-01", "arsenal", 1, 0),
        _m("1982-01-08", "watford", 0, 1),
        dict(_m("1982-01-15", "everton", 0, 0), ft_home="", ft_away=""),
    ])
    ms = runs.matches_in_order(conn, Filters(club=CLUB))
    assert not runs.longest(ms, "without-win").bounded


def test_an_ordinary_run_is_measured_across_its_own_matches(conn):
    ms = runs.matches_in_order(conn, Filters(club=CLUB))
    run = runs.longest(ms, "unbeaten")
    assert run.days == 14, "28 August to 11 September"
    assert run.bounded, "a run of its own matches is bounded by definition"
