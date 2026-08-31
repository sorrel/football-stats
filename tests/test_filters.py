"""The filter vocabulary.

The security property matters as much as the behaviour: a filter must never
put a value into the SQL text.
"""

from football.analysis.filters import Filters, select

CLUB = "brighton-hove-albion"


def test_a_question_is_always_asked_from_one_club_s_point_of_view():
    where, params = Filters(club=CLUB).where()
    assert "cm.club = ?" in where
    assert params == ["brighton-hove-albion"]


def test_values_are_bound_never_interpolated():
    nasty = "'; DROP TABLE matches; --"
    where, params = Filters(club=CLUB, opponent=nasty).where()
    assert nasty not in where, "the value must not appear in the SQL text"
    assert nasty in params


def test_filters_combine_with_and():
    where, params = Filters(club=CLUB, competition="fa-cup", side="away").where()
    assert where.count("AND") >= 2
    assert "fa-cup" in params


def test_home_excludes_matches_on_a_neutral_ground():
    """A cup final at Wembley is not a home match, whoever is listed first."""
    where, _ = Filters(club=CLUB, side="home").where()
    assert "neutral" in where


def test_neutral_is_its_own_side():
    where, _ = Filters(club=CLUB, side="neutral").where()
    assert "cm.neutral = 1" in where


def test_season_bounds_are_inclusive_ranges():
    where, params = Filters(club=CLUB, season_from="1979-80", season_to="1982-83").where()
    assert "cm.season >= ?" in where and "cm.season <= ?" in where
    assert params[1:] == ["1979-80", "1982-83"]


def test_day_names_are_capitalised_to_match_the_view():
    _, params = Filters(club=CLUB, day="saturday").where()
    assert "Saturday" in params


def test_league_only_reaches_through_to_the_club_table():
    where, _ = Filters(club=CLUB, english_league_only=True).where()
    assert "opp.english_league = 1" in where


def test_tier_reaches_through_to_the_competition_table():
    where, params = Filters(club=CLUB, tier=1).where()
    assert "m.tier = ?" in where and 1 in params


def test_select_assembles_a_full_statement():
    sql, params = select("COUNT(*)", Filters(club=CLUB, competition="fa-cup"),
                         order="cm.date", limit=5)
    assert sql.startswith("SELECT COUNT(*)")
    assert "ORDER BY cm.date" in sql and "LIMIT ?" in sql
    assert params[-1] == 5


def test_describe_reads_as_english():
    described = Filters(club=CLUB, competition="fa-cup", side="away", day="saturday").describe()
    assert "fa cup" in described and "away" in described and "Saturday" in described


def test_describe_says_so_when_nothing_is_filtered():
    assert Filters(club=CLUB).describe() == "all matches"
