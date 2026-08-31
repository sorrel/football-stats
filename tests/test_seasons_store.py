from football import schema, store


def _season(**overrides):
    row = {name: "" for name in schema.SEASONS.field_names()}
    row.update({"season_id": "1982-83_brighton-hove-albion_division-one",
                "club": "brighton-hove-albion", "season": "1982-83",
                "competition": "division-one", "tier": "1",
                "position": "22", "points": "40", "source": "fjelstul"})
    row.update(overrides)
    return row


def test_the_table_is_keyed_by_a_composite_id():
    assert schema.SEASONS.key == "season_id"
    assert "season_id" in schema.SEASONS.field_names()


def test_played_and_won_are_not_stored():
    """They are computable from the matches; a second copy could disagree."""
    names = schema.SEASONS.field_names()
    for derived in ("played", "won", "drawn", "lost", "goals_for"):
        assert derived not in names


def test_write_then_read_round_trips(tmp_path):
    store.write_seasons(tmp_path, [_season()])
    assert store.read_seasons(tmp_path) == [_season()]


def test_rows_are_sorted_for_stable_diffs(tmp_path):
    store.write_seasons(tmp_path, [
        _season(season_id="1999-00_a_b"), _season(season_id="1920-21_a_b")])
    lines = (tmp_path / "seasons.csv").read_text().splitlines()
    assert lines[1].startswith("1920-21")


def test_a_missing_file_reads_as_no_seasons(tmp_path):
    assert store.read_seasons(tmp_path) == []


def test_writing_merges_rather_than_replacing(tmp_path):
    store.write_seasons(tmp_path, [_season(season_id="a")])
    store.write_seasons(tmp_path, [_season(season_id="b")])
    assert len(store.read_seasons(tmp_path)) == 2


def test_an_unknown_position_is_empty_not_zero(tmp_path):
    store.write_seasons(tmp_path, [_season(position="")])
    assert store.read_seasons(tmp_path)[0]["position"] == ""
