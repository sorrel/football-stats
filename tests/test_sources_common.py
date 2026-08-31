"""The helpers every source shares."""

import pytest

from football.sources.common import (
    clean, parse_attendance, parse_score, season_label)


@pytest.mark.parametrize("value", ["", "NA", "None", "N/A", "  ", "-"])
def test_the_ways_sources_say_they_do_not_know(value):
    assert clean(value) == ""


def test_a_real_value_survives_cleaning():
    assert clean("  Wembley ") == "Wembley"




def test_a_season_label_spans_two_years():
    assert season_label(1982) == "1982-83"
    assert season_label("1999") == "1999-00"
    assert season_label(2025) == "2025-26"



def test_an_attendance_loses_its_separators():
    assert parse_attendance("31,729") == "31729"
    assert parse_attendance("100 000") == "100000"


def test_a_stated_zero_is_kept():
    """Behind closed doors really was no crowd."""
    assert parse_attendance("0 ([[Behind closed doors]])") == "0"


def test_an_absent_attendance_is_empty():
    assert parse_attendance("NA") == "" and parse_attendance("") == ""


def test_a_score_splits_on_either_kind_of_dash():
    assert parse_score("2-1") == ("2", "1")
    assert parse_score("2–1") == ("2", "1")


def test_an_unreadable_score_is_empty():
    assert parse_score("NA") == ("", "") and parse_score("abc") == ("", "")


def test_a_crowd_in_scientific_notation_is_read_properly():
    """engsoccerdata records nine League Cup finals as `1e+05`; read as a
    leading digit run that is 1, five orders of magnitude out."""
    assert parse_attendance("1e+05") == "100000"
    assert parse_attendance("1.5e+04") == "15000"


def test_ordinary_figures_are_unaffected():
    assert parse_attendance("100,000") == "100000"
    assert parse_attendance("31,729") == "31729"
