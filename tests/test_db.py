import pytest

from football import db, schema, store


def _minimal_data(tmp_path, matches):
    store.write_table(tmp_path, schema.CLUBS, [
        {"slug": "brighton-and-hove-albion", "name": "Brighton and Hove Albion",
         "former_names": "", "english_league": "true", "country": "England"},
        {"slug": "manchester-united", "name": "Manchester United",
         "former_names": "", "english_league": "true", "country": "England"},
    ])
    store.write_table(tmp_path, schema.COMPETITIONS, [
        {"slug": "fa-cup", "name": "FA Cup", "type": "domestic-cup", "tier": "", "first_season": "1871-72",
         "last_season": ""},
    ])
    store.write_table(tmp_path, schema.VENUES, [
        {"slug": "wembley", "name": "Wembley Stadium", "city": "London", "club": ""},
    ])
    store.write_matches(tmp_path, matches)


def _match(**overrides):
    row = {name: "" for name in schema.MATCHES.field_names()}
    row.update({
        "match_id": "1983-05-21_brighton-and-hove-albion_manchester-united",
        "date": "1983-05-21", "season": "1982-83",
        "home_club": "brighton-and-hove-albion", "away_club": "manchester-united",
        "competition": "fa-cup", "venue": "wembley",
        "ht_home": "1", "ht_away": "1", "ft_home": "2", "ft_away": "2",
        "aet_home": "2", "aet_away": "2", "status": "played", "source": "test",
    })
    row.update(overrides)
    return row


def test_build_loads_every_match(tmp_path):
    _minimal_data(tmp_path, [_match()])
    conn = db.build(tmp_path, tmp_path / "football.db")
    assert conn.execute("SELECT COUNT(*) FROM matches").fetchone()[0] == 1


def test_a_match_referring_to_an_unknown_club_fails_the_build(tmp_path):
    _minimal_data(tmp_path, [_match(away_club="atlantis-fc")])
    with pytest.raises(db.ValidationError, match="atlantis-fc"):
        db.build(tmp_path, tmp_path / "football.db")


def test_two_matches_between_the_same_clubs_on_one_date_fail_the_build(tmp_path):
    duplicate = _match(match_id="another-id")
    _minimal_data(tmp_path, [_match(), duplicate])
    with pytest.raises(db.ValidationError, match="duplicate"):
        db.build(tmp_path, tmp_path / "football.db")


def test_club_matches_view_shows_both_sides_without_duplicating_storage(tmp_path):
    _minimal_data(tmp_path, [_match()])
    conn = db.build(tmp_path, tmp_path / "football.db")
    rows = conn.execute(
        "SELECT club, opponent, home_or_away FROM club_matches ORDER BY club"
    ).fetchall()
    assert rows == [
        ("brighton-and-hove-albion", "manchester-united", "H"),
        ("manchester-united", "brighton-and-hove-albion", "A"),
    ]
    assert conn.execute("SELECT COUNT(*) FROM matches").fetchone()[0] == 1


def test_cards_are_swapped_for_against_the_same_way_goals_are(tmp_path):
    _minimal_data(tmp_path, [_match(
        home_yellows="2", away_yellows="3", home_reds="1", away_reds="0")])
    conn = db.build(tmp_path, tmp_path / "football.db")
    rows = {row[0]: row[1:] for row in conn.execute(
        "SELECT home_or_away, yellows_for, yellows_against, reds_for, "
        "reds_against FROM club_matches")}
    assert rows["H"] == (2, 3, 1, 0)
    assert rows["A"] == (3, 2, 0, 1)


def test_result_is_decided_after_ninety_minutes(tmp_path):
    _minimal_data(tmp_path, [_match(ft_home="1", ft_away="0", aet_home="", aet_away="")])
    conn = db.build(tmp_path, tmp_path / "football.db")
    result = conn.execute(
        "SELECT result FROM club_matches WHERE home_or_away = 'H'"
    ).fetchone()[0]
    assert result == "W"


def test_final_result_accounts_for_extra_time_and_penalties(tmp_path):
    _minimal_data(tmp_path, [_match(
        ft_home="1", ft_away="1", aet_home="1", aet_away="1",
        pens_home="4", pens_away="3")])
    conn = db.build(tmp_path, tmp_path / "football.db")
    rows = dict(conn.execute(
        "SELECT home_or_away, final_result FROM club_matches").fetchall())
    assert rows == {"H": "W", "A": "L"}


def test_final_result_follows_extra_time_when_there_was_no_shootout(tmp_path):
    _minimal_data(tmp_path, [_match(
        ft_home="1", ft_away="1", aet_home="2", aet_away="1")])
    conn = db.build(tmp_path, tmp_path / "football.db")
    rows = dict(conn.execute(
        "SELECT home_or_away, final_result FROM club_matches").fetchall())
    assert rows == {"H": "W", "A": "L"}


def test_day_of_week_is_derived_from_the_date(tmp_path):
    _minimal_data(tmp_path, [_match()])  # 21 May 1983 was a Saturday
    conn = db.build(tmp_path, tmp_path / "football.db")
    assert conn.execute(
        "SELECT day_of_week FROM club_matches LIMIT 1").fetchone()[0] == "Saturday"


def test_the_same_tie_on_two_dates_fails_the_build(tmp_path):
    """A corrected date leaves the old row behind, since the id embeds it."""
    _minimal_data(tmp_path, [
        _match(match_id="a", date="2019-08-01", round="Final"),
        _match(match_id="b", date="2020-08-01", round="Final")])
    with pytest.raises(db.ValidationError, match="the same tie appears twice"):
        db.build(tmp_path, tmp_path / "f.db")


def test_a_replay_is_not_a_repeated_tie(tmp_path):
    _minimal_data(tmp_path, [
        _match(match_id="a", date="1983-05-21", round="Final"),
        _match(match_id="b", date="1983-05-26", round="Final",
               is_replay="true", replay_of="a")])
    assert db.build(tmp_path, tmp_path / "f.db")


def test_a_two_legged_tie_is_not_a_repeated_tie(tmp_path):
    _minimal_data(tmp_path, [
        _match(match_id="a", date="1991-05-19", round="Semi-final", leg="1"),
        _match(match_id="b", date="1991-05-22", round="Semi-final", leg="2")])
    assert db.build(tmp_path, tmp_path / "f.db")


def test_a_league_season_is_not_a_repeated_tie(tmp_path):
    """League matches have no round, and clubs meet twice a season."""
    _minimal_data(tmp_path, [
        _match(match_id="a", date="1982-09-04"),
        _match(match_id="b", date="1983-04-02")])
    assert db.build(tmp_path, tmp_path / "f.db")
