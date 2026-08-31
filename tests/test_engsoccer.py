"""Tests for the engsoccerdata importer.

Fixtures are hand-written rows in the source's shape, not saved files: the
awkward cases (extra time, a replay, a bye) matter more than volume.
"""

import pytest

from football.sources import engsoccer


def _league(**overrides):
    record = {"Date": "1983-04-02", "Season": "1982", "home": "Brighton & Hove Albion",
              "visitor": "Crystal Palace", "FT": "3-1", "hgoal": "3", "vgoal": "1",
              "division": "1", "tier": "1"}
    record.update(overrides)
    return record


def _cup(**overrides):
    record = {"Date": "1983-05-21", "Season": "1982", "home": "Manchester United",
              "visitor": "Brighton & Hove Albion", "FT": "2-2", "round": "f",
              "tie": "initial",
              "aet": "NA", "pen": "NA", "pens": "NA", "hp": "NA", "vp": "NA",
              "Venue": "Wembley (original), London", "attendance": "100,000",
              "nonmatch": "NA", "notes": "NA", "neutral": "yes"}
    record.update(overrides)
    return record


def test_season_label_spans_two_calendar_years():
    assert engsoccer.season_label(1982) == "1982-83"
    assert engsoccer.season_label(1999) == "1999-00"
    assert engsoccer.season_label(2025) == "2025-26"


def test_attendance_loses_its_thousands_separator():
    assert engsoccer.parse_attendance("100,000") == "100000"
    assert engsoccer.parse_attendance("NA") == ""


def test_a_league_match_records_the_ninety_minute_score():
    row = engsoccer.league_match(_league())
    assert (row["ft_home"], row["ft_away"]) == ("3", "1")
    assert row["aet_home"] == "" and row["pens_home"] == ""
    assert row["source"] == "engsoccerdata"


def test_tier_one_is_named_for_its_era():
    assert engsoccer.league_competition("1", 1982)[0] == "division-one"
    assert engsoccer.league_competition("1", 1992)[0] == "premier-league"
    assert engsoccer.league_competition("2", 2004)[0] == "championship"
    assert engsoccer.league_competition("2", 1991)[0] == "division-two"


def test_a_cup_tie_without_extra_time_records_a_full_time_score():
    row = engsoccer.facup_match(_cup(aet="NA", FT="1-0"))
    assert (row["ft_home"], row["ft_away"]) == ("1", "0")
    assert row["aet_home"] == ""


def test_extra_time_is_not_filed_as_the_ninety_minute_score():
    """`FT` includes extra time when `aet` is set, so 90 minutes is unknown."""
    row = engsoccer.facup_match(_cup(aet="yes", FT="2-2"))
    assert (row["aet_home"], row["aet_away"]) == ("2", "2")
    assert row["ft_home"] == "" and row["ft_away"] == "", (
        "recording an extra-time score as the full-time score would corrupt "
        "every goals-in-extra-time figure"
    )


def test_a_shootout_is_recorded_as_its_own_tally():
    row = engsoccer.facup_match(_cup(aet="yes", FT="1-1", pen="yes", hp="4", vp="3"))
    assert (row["pens_home"], row["pens_away"]) == ("4", "3")
    assert (row["aet_home"], row["aet_away"]) == ("1", "1")


def test_cup_metadata_is_carried_across():
    row = engsoccer.facup_match(_cup())
    assert row["round"] == "Final"
    assert row["attendance"] == "100000"
    assert row["neutral"] == "true"
    assert row["venue"] == "wembley-original"


def test_numbered_rounds_are_named():
    assert engsoccer.round_name("3") == "Round 3"
    assert engsoccer.round_name("s") == "Semi-final"


def test_a_bye_is_not_a_match():
    assert not engsoccer.is_real_match(_cup(nonmatch="Bye", FT="NA"))
    assert engsoccer.is_real_match(_cup())


def test_the_replay_of_a_tie_points_at_the_original():
    first = engsoccer.facup_match(_cup(Date="1983-05-21", FT="2-2", aet="yes",
                                       tie="initial"))
    second = engsoccer.facup_match(_cup(Date="1983-05-26", FT="4-0", tie="replay"))
    engsoccer.link_replays([second, first])
    assert first["is_replay"] == ""
    assert second["is_replay"] == "true"
    assert second["replay_of"] == first["match_id"]


def test_a_league_fixture_is_never_mistaken_for_a_replay():
    """Clubs meet twice a season, home and away — that is not a replay."""
    home = engsoccer.league_match(_league(Date="1982-09-04"))
    away = engsoccer.league_match(_league(
        Date="1983-04-02", home="Crystal Palace", visitor="Brighton & Hove Albion"))
    engsoccer.link_replays([home, away])
    assert home["is_replay"] == "" and away["is_replay"] == ""


def test_competitions_do_not_claim_a_span_they_cannot_know():
    """One club's matches from one source cannot say when a competition ran."""
    rows = [engsoccer.league_match(_league(Season="1982")),
            engsoccer.league_match(_league(Season="1984", Date="1985-04-02"))]
    competitions = engsoccer.competitions_from(rows)
    assert competitions[0]["first_season"] == ""
    assert competitions[0]["last_season"] == ""


def test_selecting_a_club_keeps_both_home_and_away_records():
    records = [_league(), _league(home="Arsenal", visitor="Chelsea")]
    kept = list(engsoccer.select_club(records, "Brighton & Hove Albion"))
    assert len(kept) == 1


def test_the_match_id_does_not_depend_on_which_club_was_selected():
    row = engsoccer.league_match(_league())
    assert row["match_id"] == (
        "1983-04-02_brighton-hove-albion_crystal-palace")


@pytest.mark.parametrize("text,expected", [
    ("2-2", ("2", "2")), ("10-0", ("10", "0")), ("NA", ("", "")), ("", ("", "")),
])
def test_parse_score(text, expected):
    assert engsoccer.parse_score(text) == expected


def test_a_club_absent_from_the_league_file_is_not_an_english_league_club():
    """Non-League cup opposition must not be flagged as a League club."""
    rows = [engsoccer.facup_match(_cup(home="Brighton & Hove Albion",
                                       visitor="Wisbech Town", FT="10-1"))]
    league_clubs = engsoccer.league_club_slugs([_league()])
    clubs = {c["slug"]: c["english_league"]
             for c in engsoccer.clubs_from(rows, {}, league_clubs)}
    assert clubs["brighton-hove-albion"] == "true"
    assert clubs["wisbech-town"] == "false"


def test_without_the_league_file_nothing_is_claimed():
    rows = [engsoccer.league_match(_league())]
    clubs = engsoccer.clubs_from(rows, {})
    assert all(c["english_league"] == "" for c in clubs), (
        "unknown must not be recorded as a claim either way"
    )


def test_the_regional_third_divisions_are_their_own_competitions():
    """From 1921-22 to 1957-58 the Third Division was North and South."""
    south = engsoccer.league_competition("3", 1935, division="3S")
    north = engsoccer.league_competition("3", 1935, division="3N")
    assert south[0] == "division-three-south"
    assert north[0] == "division-three-north"
    assert south[1] == "Third Division South"


def test_a_regional_division_is_still_tier_three():
    """The tier was always right; only the name was wrong."""
    assert engsoccer.league_competition("3", 1935, division="3S")[2] == 3


def test_the_national_third_division_is_unaffected():
    """1920-21 and 1958-59 onwards were a single Third Division."""
    assert engsoccer.league_competition("3", 1920, division="3")[0] == "division-three"
    assert engsoccer.league_competition("3", 1960, division="3")[0] == "division-three"


def test_tier_three_after_2004_is_still_league_one():
    assert engsoccer.league_competition("3", 2005, division="3")[0] == "league-one"


def test_a_league_match_records_the_regional_division():
    row = engsoccer.league_match(_league(Season="1935", tier="3", division="3S",
                                         Date="1936-04-02"))
    assert row["competition"] == "division-three-south"
    assert row["tier"] == "3"
