import tempfile
from pathlib import Path

import pytest

from football import db, schema, store
from football.analysis.seasons import cup_runs, season_rows
from football.parse.base import blank_row


def _match(date, season, competition, opponent, gf, ga, tier="", round_="",
           home=True):
    row = blank_row(schema.MATCHES)
    us = "brighton-hove-albion"
    row.update({
        "match_id": f"{date}_{us if home else opponent}_{opponent if home else us}",
        "date": date, "season": season, "competition": competition,
        "home_club": us if home else opponent,
        "away_club": opponent if home else us,
        "tier": tier, "round": round_, "status": "played", "source": "test",
        "ft_home": str(gf if home else ga), "ft_away": str(ga if home else gf),
    })
    return row


def _competition(slug, name, type_):
    return {"slug": slug, "name": name, "type": type_, "tier": "",
            "first_season": "", "last_season": ""}


@pytest.fixture
def conn(tmp_path):
    store.write_table(tmp_path, schema.CLUBS, [
        {"slug": s, "name": s, "former_names": "", "english_league": "true",
         "country": "England"}
        for s in ("brighton-hove-albion", "watford", "arsenal", "millwall")])
    store.write_table(tmp_path, schema.COMPETITIONS, [
        _competition("division-two", "Division Two", "league"),
        _competition("division-one", "Division One", "league"),
        _competition("division-two-play-offs", "Division Two Play-offs", "play-off"),
        _competition("fa-cup", "FA Cup", "domestic-cup")])
    store.write_table(tmp_path, schema.VENUES, [])
    store.write_matches(tmp_path, [
        _match("1979-04-01", "1978-79", "division-two", "watford", 2, 0, tier="2"),
        _match("1980-04-01", "1979-80", "division-one", "arsenal", 1, 1, tier="1"),
        _match("1991-05-19", "1990-91", "division-two", "watford", 1, 0, tier="2"),
        _match("1991-05-25", "1990-91", "division-two-play-offs", "millwall",
               4, 1, tier="2", round_="Semi-final"),
        _match("1992-04-01", "1991-92", "division-two", "arsenal", 0, 1, tier="2"),
        _match("1983-01-08", "1982-83", "fa-cup", "arsenal", 2, 1, round_="Round 3"),
        _match("1983-05-21", "1982-83", "fa-cup", "watford", 2, 2, round_="Final"),
    ])
    store.write_seasons(tmp_path, [
        {**{n: "" for n in schema.SEASONS.field_names()},
         "season_id": "1978-79_brighton-hove-albion_division-two",
         "club": "brighton-hove-albion", "season": "1978-79",
         "competition": "division-two", "tier": "2", "position": "2",
         "points": "56", "source": "test"}])
    return db.build(tmp_path, tmp_path / "f.db")


def test_a_season_carries_its_stored_position(conn):
    rows = dict((s.season, s) for s, _ in season_rows(conn, "brighton-hove-albion"))
    assert rows["1978-79"].position == 2


def test_a_season_with_no_stored_position_is_still_listed(conn):
    """The matches are the record of what was played; the table may be missing."""
    seasons = [s.season for s, _ in season_rows(conn, "brighton-hove-albion")]
    assert "1979-80" in seasons


def test_promotion_is_derived_from_the_tiers(conn):
    outcomes = dict((s.season, o) for s, o in season_rows(conn, "brighton-hove-albion"))
    assert outcomes["1978-79"] == "promoted"


def test_a_season_with_play_off_matches_that_stayed_up_lost_them(conn):
    outcomes = dict((s.season, o) for s, o in season_rows(conn, "brighton-hove-albion"))
    assert outcomes["1990-91"] == "play-offs-lost"


def test_play_off_matches_do_not_become_a_league_season(conn):
    """They are an addendum to the league season, not a season of their own."""
    competitions = {s.competition for s, _ in season_rows(conn, "brighton-hove-albion")}
    assert "division-two-play-offs" not in competitions


def test_the_last_season_is_the_current_one_not_stayed(conn):
    """It has not resolved yet, which is not the same as staying up."""
    outcomes = dict((s.season, o) for s, o in season_rows(conn, "brighton-hove-albion"))
    assert outcomes["1991-92"] == "current"


def test_a_cup_run_reports_how_far_it_went(conn):
    runs = cup_runs(conn, "brighton-hove-albion")
    # No league match is held for 1982-83, so the tier is unknown and the
    # run is judged on neither: a run reaching the final either way.
    assert runs == [("1982-83", "FA Cup", "Final", "Runners-up", "final")]


def test_a_cup_run_that_ended_in_a_win_says_winners(tmp_path):
    store.write_table(tmp_path, schema.CLUBS, [
        {"slug": s, "name": s, "former_names": "", "english_league": "true",
         "country": "England"} for s in ("brighton-hove-albion", "watford")])
    store.write_table(tmp_path, schema.COMPETITIONS, [
        _competition("fa-cup", "FA Cup", "domestic-cup")])
    store.write_table(tmp_path, schema.VENUES, [])
    store.write_matches(tmp_path, [
        _match("1983-05-21", "1982-83", "fa-cup", "watford", 4, 0, round_="Final")])
    conn = db.build(tmp_path, tmp_path / "f.db")
    assert cup_runs(conn, "brighton-hove-albion")[0][3] == "Winners"
    assert cup_runs(conn, "brighton-hove-albion")[0][4] == "winners"


def test_the_top_four_rounds_are_each_their_own_category(tmp_path):
    store.write_table(tmp_path, schema.CLUBS, [
        {"slug": s, "name": s, "former_names": "", "english_league": "true",
         "country": "England"} for s in ("brighton-hove-albion", "watford")])
    store.write_table(tmp_path, schema.COMPETITIONS, [
        _competition("fa-cup", "FA Cup", "domestic-cup")])
    store.write_table(tmp_path, schema.VENUES, [])
    store.write_matches(tmp_path, [
        _match("1983-01-08", "1982-83", "fa-cup", "watford", 2, 1,
               round_="Quarter-final")])
    conn = db.build(tmp_path, tmp_path / "f.db")
    assert cup_runs(conn, "brighton-hove-albion")[0][4] == "quarter-final"


def test_an_early_exit_is_poor_for_a_league_one_or_two_club(tmp_path):
    """League One and Two: an exit as late as round 1 is unremarkable, but
    the record must hold a league season to know the level was that low."""
    store.write_table(tmp_path, schema.CLUBS, [
        {"slug": s, "name": s, "former_names": "", "english_league": "true",
         "country": "England"} for s in ("brighton-hove-albion", "watford")])
    store.write_table(tmp_path, schema.COMPETITIONS, [
        _competition("division-three", "Division Three", "league"),
        _competition("fa-cup", "FA Cup", "domestic-cup")])
    store.write_table(tmp_path, schema.VENUES, [])
    store.write_matches(tmp_path, [
        _match("1982-09-04", "1982-83", "division-three", "watford", 1, 0, tier="3"),
        _match("1983-01-08", "1982-83", "fa-cup", "watford", 0, 1, round_="Round 1")])
    conn = db.build(tmp_path, tmp_path / "f.db")
    assert cup_runs(conn, "brighton-hove-albion")[0][4] == "early-exit"


def test_the_same_round_is_not_poor_for_a_top_flight_club(tmp_path):
    """A round 1 exit from a First Division club is a letdown, but round 4
    is not — only a Championship-or-above exit at round 3 or before is."""
    store.write_table(tmp_path, schema.CLUBS, [
        {"slug": s, "name": s, "former_names": "", "english_league": "true",
         "country": "England"} for s in ("brighton-hove-albion", "watford")])
    store.write_table(tmp_path, schema.COMPETITIONS, [
        _competition("division-one", "Division One", "league"),
        _competition("fa-cup", "FA Cup", "domestic-cup")])
    store.write_table(tmp_path, schema.VENUES, [])
    store.write_matches(tmp_path, [
        _match("1982-09-04", "1982-83", "division-one", "watford", 1, 0, tier="1"),
        _match("1983-01-08", "1982-83", "fa-cup", "watford", 2, 1, round_="Round 4")])
    conn = db.build(tmp_path, tmp_path / "f.db")
    assert cup_runs(conn, "brighton-hove-albion")[0][4] == ""


def test_round_three_is_poor_for_a_top_flight_club(tmp_path):
    store.write_table(tmp_path, schema.CLUBS, [
        {"slug": s, "name": s, "former_names": "", "english_league": "true",
         "country": "England"} for s in ("brighton-hove-albion", "watford")])
    store.write_table(tmp_path, schema.COMPETITIONS, [
        _competition("division-one", "Division One", "league"),
        _competition("fa-cup", "FA Cup", "domestic-cup")])
    store.write_table(tmp_path, schema.VENUES, [])
    store.write_matches(tmp_path, [
        _match("1982-09-04", "1982-83", "division-one", "watford", 1, 0, tier="1"),
        _match("1983-01-08", "1982-83", "fa-cup", "watford", 0, 1, round_="Round 3")])
    conn = db.build(tmp_path, tmp_path / "f.db")
    assert cup_runs(conn, "brighton-hove-albion")[0][4] == "early-exit"


def test_synonymous_rounds_share_a_rank():
    """The FA Cup fifth round is the round of 16; sources name it both ways."""
    from football.analysis.seasons import _round_rank
    assert _round_rank("Round 5") == _round_rank("Round of 16")
    assert _round_rank("Round 6") == _round_rank("Quarter-final")


def test_the_round_of_16_comes_before_the_quarter_final():
    """It ranked above it before synonyms were unified."""
    from football.analysis.seasons import _round_rank
    assert _round_rank("Round of 16") < _round_rank("Quarter-final")
    assert _round_rank("Quarter-final") < _round_rank("Semi-final")
    assert _round_rank("Semi-final") < _round_rank("Final")


def test_a_group_stage_comes_before_the_knockout_rounds():
    from football.analysis.seasons import _round_rank
    assert _round_rank("Group B") < _round_rank("Round of 16")


def test_a_group_stage_is_shown_as_group_stage_not_its_own_letter():
    """A supporter compares a season's group form to another's, not Group C
    to Group F — the letter is a detail nobody asked this for."""
    conn = _seed_cups(("europa-league", "Europa League", "europe"), [
        _match("2023-09-14", "2023-24", "europa-league", "watford", 1, 1,
               round_="Group F")])
    assert cup_runs(conn, "brighton-hove-albion")[0][3] == "Group Stage"


def test_two_cups_in_a_season_also_get_a_combined_row(tmp_path):
    conn = _seed_cups(
        [("fa-cup", "FA Cup", "domestic-cup"),
         ("league-cup", "League Cup", "domestic-cup")],
        [_match("1982-09-01", "1982-83", "fa-cup", "watford", 1, 0,
                round_="Quarter-final"),
         _match("1982-10-01", "1982-83", "league-cup", "arsenal", 0, 1,
                round_="Round 2")])
    runs = cup_runs(conn, "brighton-hove-albion")
    labels = [row[1] for row in runs]
    assert labels == ["FA Cup", "League Cup", "Combined"]
    combined = runs[-1]
    assert (combined[2], combined[3]) == ("Quarter-final", "Quarter-final")


def test_a_lone_competition_gets_no_combined_row_of_its_own():
    """It would only repeat the one entry already there."""
    conn = _seed_cups(("fa-cup", "FA Cup", "domestic-cup"), [
        _match("1982-09-01", "1982-83", "fa-cup", "watford", 1, 0,
               round_="Quarter-final")])
    runs = cup_runs(conn, "brighton-hove-albion")
    assert [row[1] for row in runs] == ["FA Cup"]


def _seed_cups(competitions, matches):
    """A minimal database for one club, its opponents, and the given cups."""
    club = "brighton-hove-albion"
    opponents = {m["home_club"] for m in matches} | {m["away_club"] for m in matches}
    tmp_path = Path(tempfile.mkdtemp())
    store.write_table(tmp_path, schema.CLUBS, [
        {"slug": s, "name": s, "former_names": "", "english_league": "true",
         "country": "England"} for s in sorted(opponents | {club})])
    comps = [competitions] if isinstance(competitions[0], str) else competitions
    store.write_table(tmp_path, schema.COMPETITIONS, [_competition(*c) for c in comps])
    store.write_table(tmp_path, schema.VENUES, [])
    store.write_matches(tmp_path, matches)
    return db.build(tmp_path, tmp_path / "f.db")
