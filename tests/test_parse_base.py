import pytest

from football import schema
from football.parse.base import InconsistentScore, ParsedPage, blank_row, check_scores


def test_blank_row_has_every_declared_column_and_nothing_else():
    row = blank_row(schema.MATCHES)
    assert set(row) == set(schema.MATCHES.field_names())
    assert all(value == "" for value in row.values())


def test_a_parsed_page_defaults_to_no_records():
    page = ParsedPage()
    assert page.matches == [] and page.clubs == []


def test_half_time_goals_may_not_exceed_full_time_goals():
    row = blank_row(schema.MATCHES)
    row.update({"ht_home": "3", "ht_away": "0", "ft_home": "1", "ft_away": "0"})
    with pytest.raises(InconsistentScore, match="half-time"):
        check_scores(row)


def test_extra_time_goals_may_not_be_fewer_than_at_full_time():
    row = blank_row(schema.MATCHES)
    row.update({"ft_home": "2", "ft_away": "1", "aet_home": "1", "aet_away": "1"})
    with pytest.raises(InconsistentScore, match="extra time"):
        check_scores(row)


def test_a_shootout_score_is_not_treated_as_a_running_total():
    """A 1-1 draw won 4-3 on penalties is consistent, not a scoring explosion."""
    row = blank_row(schema.MATCHES)
    row.update({"ht_home": "0", "ht_away": "1", "ft_home": "1", "ft_away": "1",
                "aet_home": "1", "aet_away": "1", "pens_home": "4", "pens_away": "3"})
    check_scores(row)  # must not raise


def test_a_drawn_shootout_is_impossible():
    row = blank_row(schema.MATCHES)
    row.update({"ft_home": "1", "ft_away": "1", "pens_home": "3", "pens_away": "3"})
    with pytest.raises(InconsistentScore, match="shootout"):
        check_scores(row)


def test_unknown_scores_are_permitted():
    check_scores(blank_row(schema.MATCHES))  # must not raise
