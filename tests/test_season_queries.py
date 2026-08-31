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
    assert runs == [("1982-83", "fa-cup", "Final", "Runners-up")]


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
