from football import corrections, schema
from football.parse.base import blank_row


def _match(**overrides):
    row = blank_row(schema.MATCHES)
    row.update({"match_id": "m1", "date": "1983-05-21", "season": "1982-83",
                "home_club": "a", "away_club": "b", "competition": "fa-cup",
                "aet_home": "2", "aet_away": "2", "source": "engsoccerdata"})
    row.update(overrides)
    return row


def _correction(**overrides):
    row = blank_row(schema.MATCHES)
    row["match_id"] = "m1"
    row.update(overrides)
    return row


def test_a_correction_fills_in_what_the_source_did_not_know():
    rows = corrections.apply([_match()], [_correction(ht_home="1", ht_away="0")])
    assert (rows[0]["ht_home"], rows[0]["ht_away"]) == ("1", "0")


def test_empty_cells_in_a_correction_leave_the_row_alone():
    """A correction is sparse: it supplies only what it knows."""
    rows = corrections.apply([_match()], [_correction(ht_home="1")])
    assert rows[0]["aet_home"] == "2", "an unrelated field must not be blanked"


def test_a_correction_overrides_a_value_the_source_got_wrong():
    rows = corrections.apply([_match(ft_home="9")], [_correction(ft_home="2")])
    assert rows[0]["ft_home"] == "2"


def test_a_corrected_match_is_marked_as_such():
    rows = corrections.apply([_match()], [_correction(ht_home="1")])
    assert rows[0]["source"] == "engsoccerdata+manual"


def test_marking_does_not_accumulate_on_repeated_application():
    rows = corrections.apply([_match()], [_correction(ht_home="1")])
    rows = corrections.apply(rows, [_correction(ht_home="1")])
    assert rows[0]["source"] == "engsoccerdata+manual"


def test_a_correction_that_changes_nothing_does_not_mark_the_row():
    rows = corrections.apply([_match(ht_home="1")], [_correction(ht_home="1")])
    assert rows[0]["source"] == "engsoccerdata"


def test_identity_fields_are_never_overwritten():
    """Changing a date or a club would make it a different match entirely."""
    rows = corrections.apply([_match()], [_correction(date="1999-01-01",
                                                      home_club="zzz")])
    assert rows[0]["date"] == "1983-05-21"
    assert rows[0]["home_club"] == "a"


def test_a_correction_for_an_unknown_match_is_ignored_not_inserted():
    rows = corrections.apply([_match()], [_correction(match_id="nope", ht_home="1")])
    assert len(rows) == 1


def test_unmatched_corrections_can_be_reported():
    assert corrections.unmatched([_match()], [_correction(match_id="nope")]) == ["nope"]


def test_no_corrections_file_means_no_corrections(tmp_path):
    assert corrections.read(tmp_path) == []
