"""Deriving promotion, relegation and the play-offs.

The fixtures are real Brighton seasons, so a wrong rule fails against
history rather than against an invented example.
"""

import pytest

from football.analysis.seasons import LeagueSeason, outcome


def _s(season, tier, position="10", play_offs=False):
    return LeagueSeason(season=season, competition="x", tier=int(tier),
                        position=int(position), points=None,
                        point_adjustment=None, played_play_offs=play_offs)


def test_a_lower_tier_next_season_is_promotion():
    seasons = [_s("1978-79", 2, "2"), _s("1979-80", 1)]
    assert outcome(seasons, 0) == "promoted"


def test_a_higher_tier_next_season_is_relegation():
    seasons = [_s("1982-83", 1, "22"), _s("1983-84", 2)]
    assert outcome(seasons, 0) == "relegated"


def test_promotion_after_play_off_matches_says_so():
    seasons = [_s("2003-04", 3, "4", play_offs=True), _s("2004-05", 2)]
    assert outcome(seasons, 0) == "promoted-via-play-offs"


def test_promotion_without_play_off_matches_is_automatic():
    seasons = [_s("2010-11", 3, "1"), _s("2011-12", 2)]
    assert outcome(seasons, 0) == "promoted"


def test_play_off_matches_and_the_same_tier_is_a_play_off_defeat():
    seasons = [_s("2015-16", 2, "3", play_offs=True), _s("2016-17", 2)]
    assert outcome(seasons, 0) == "play-offs-lost"


def test_the_same_tier_with_no_play_offs_is_simply_staying_up():
    seasons = [_s("1990-91", 2, "6"), _s("1991-92", 2)]
    assert outcome(seasons, 0) == "stayed"


def test_the_last_season_on_record_is_the_current_one():
    """It has not resolved yet; that is not the same as staying up."""
    seasons = [_s("2025-26", 1, "8")]
    assert outcome(seasons, 0) == "current"


def test_a_gap_across_the_second_world_war_says_so():
    """1938-39 was completed and counted; then football stopped."""
    seasons = [_s("1938-39", 3, "9"), _s("1946-47", 3)]
    assert outcome(seasons, 0) == "war"


def test_a_gap_across_the_first_world_war_says_so_too():
    seasons = [_s("1914-15", 2, "9"), _s("1919-20", 2)]
    assert outcome(seasons, 0) == "war"


def test_a_gap_that_is_not_wartime_is_not_called_war():
    """Accrington Stanley resigned in 1962; Barrow were voted out in 1972."""
    seasons = [_s("1961-62", 4, "9"), _s("1970-71", 4)]
    assert outcome(seasons, 0) == "left-the-league"


def test_nothing_is_ever_reported_as_unknown():
    """Every gap has a reason; "unknown" hides which."""
    cases = [
        [_s("2025-26", 1, "8")],
        [_s("1938-39", 3, "9"), _s("1946-47", 3)],
        [_s("1961-62", 4, "9"), _s("1970-71", 4)],
    ]
    for seasons in cases:
        assert outcome(seasons, 0) != "unknown"


def test_every_outcome_is_one_of_the_declared_values():
    from football.analysis.seasons import OUTCOMES
    seasons = [_s("2003-04", 3, "4", play_offs=True), _s("2004-05", 2)]
    assert outcome(seasons, 0) in OUTCOMES


@pytest.mark.parametrize("position", ["1", "24"])
def test_position_does_not_change_the_outcome(position):
    """Finishing top is read from the position, not encoded as an outcome."""
    seasons = [_s("1990-91", 2, position), _s("1991-92", 2)]
    assert outcome(seasons, 0) == "stayed"
