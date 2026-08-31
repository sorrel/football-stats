"""Comparing the sources against the database."""

from football.analysis.verify import compare, summarise, unknown_to_us


def _row(match_id="m1", **overrides):
    row = {"match_id": match_id, "date": "1983-05-21", "season": "1982-83",
           "competition": "fa-cup", "round": "Final", "ft_home": "2",
           "ft_away": "2", "attendance": "100000", "source": "a"}
    row.update(overrides)
    return row


def test_agreement_reports_nothing():
    assert compare([_row()], [_row()], "b") == []


def test_a_contradicted_value_is_reported():
    found = compare([_row(round="Quarter-final")], [_row(round="Round 5")], "b")
    assert len(found) == 1
    assert found[0].field == "round"
    assert found[0].held == "Quarter-final" and found[0].offered == "Round 5"


def test_a_blank_on_either_side_is_not_a_disagreement():
    """One source not carrying a field is the ordinary case."""
    assert compare([_row(attendance="")], [_row()], "b") == []
    assert compare([_row()], [_row(attendance="")], "b") == []


def test_provenance_is_not_compared():
    """Sources differ on `source` by definition."""
    assert compare([_row(source="a")], [_row(source="b")], "b") == []


def test_a_match_we_do_not_hold_is_not_a_disagreement():
    assert compare([_row("m1")], [_row("m2")], "b") == []


def test_matches_we_do_not_hold_are_listed_separately():
    assert unknown_to_us([_row("m1")], [_row("m1"), _row("m2")]) == ["m2"]


def test_several_fields_are_each_reported():
    found = compare([_row()], [_row(ft_home="3", attendance="99")], "b")
    assert {item.field for item in found} == {"ft_home", "attendance"}


def test_the_summary_groups_by_field_commonest_first():
    found = (compare([_row("a")], [_row("a", ft_home="9")], "b")
             + compare([_row("b")], [_row("b", ft_home="9")], "b")
             + compare([_row("c")], [_row("c", round="X")], "b"))
    rows = summarise(found)
    assert rows[0][0] == "ft_home" and rows[0][1] == 2
    assert "says" in rows[0][2]


def test_the_summary_of_nothing_is_empty():
    assert summarise([]) == []
