"""Fuzzy club matching, and the chooser when a name is ambiguous."""

import pytest

from football.analysis.clubs import Candidate, find_clubs

CLUBS = [
    Candidate("brighton-hove-albion", "Brighton and Hove Albion"),
    Candidate("west-bromwich-albion", "West Bromwich Albion"),
    Candidate("albion-rovers", "Albion Rovers"),
    Candidate("crystal-palace", "Crystal Palace"),
    Candidate("manchester-united", "Manchester United"),
    Candidate("manchester-city", "Manchester City"),
]


def test_an_exact_slug_wins_outright():
    """An exact slug must never be turned into a chooser."""
    assert find_clubs(CLUBS, "crystal-palace") == [CLUBS[3]]


def test_a_partial_name_finds_every_match():
    found = {c.slug for c in find_clubs(CLUBS, "Albion")}
    assert found == {"brighton-hove-albion", "west-bromwich-albion", "albion-rovers"}


def test_matching_ignores_case():
    assert find_clubs(CLUBS, "albion") == find_clubs(CLUBS, "ALBION")


def test_a_slug_fragment_matches_too():
    found = {c.slug for c in find_clubs(CLUBS, "manchester")}
    assert found == {"manchester-united", "manchester-city"}


def test_a_unique_partial_match_is_returned_alone():
    assert find_clubs(CLUBS, "palace") == [CLUBS[3]]


def test_nothing_matching_returns_nothing():
    assert find_clubs(CLUBS, "wanderers") == []


def test_matching_spans_words_in_the_name():
    """"hove" appears in the name but not at its start."""
    assert find_clubs(CLUBS, "hove") == [CLUBS[0]]


def test_results_are_ordered_by_name_so_the_menu_is_stable():
    found = find_clubs(CLUBS, "albion")
    assert [c.name for c in found] == sorted(c.name for c in found)


@pytest.mark.parametrize("query", ["", "   "])
def test_an_empty_query_matches_nothing(query):
    assert find_clubs(CLUBS, query) == []
