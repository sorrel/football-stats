from football import schema, store


def _match(season, match_id):
    row = {name: "" for name in schema.MATCHES.field_names()}
    row.update({"match_id": match_id, "season": season, "date": "1983-04-02",
                "home_club": "a", "away_club": "b", "competition": "c",
                "source": "test"})
    return row


def test_matches_are_written_one_file_per_season(tmp_path):
    store.write_matches(tmp_path, [_match("1982-83", "x"), _match("1983-84", "y")])
    assert (tmp_path / "matches" / "1982-83.csv").exists()
    assert (tmp_path / "matches" / "1983-84.csv").exists()


def test_reading_gathers_every_shard(tmp_path):
    store.write_matches(tmp_path, [_match("1982-83", "x"), _match("1983-84", "y")])
    assert {row["match_id"] for row in store.read_matches(tmp_path)} == {"x", "y"}


def test_writing_a_season_merges_rather_than_replacing_the_shard(tmp_path):
    """A partial write must never drop matches it did not mention."""
    store.write_matches(tmp_path, [_match("1982-83", "x")])
    store.write_matches(tmp_path, [_match("1982-83", "z")])
    assert {row["match_id"] for row in store.read_matches(tmp_path)} == {"x", "z"}


def test_writing_one_season_leaves_the_others_untouched(tmp_path):
    store.write_matches(tmp_path, [_match("1982-83", "x"), _match("1983-84", "y")])
    before = (tmp_path / "matches" / "1983-84.csv").read_bytes()
    store.write_matches(tmp_path, [_match("1982-83", "z")])
    assert (tmp_path / "matches" / "1983-84.csv").read_bytes() == before
    assert {row["match_id"] for row in store.read_matches(tmp_path)} == {"x", "z", "y"}


def test_seasons_lists_what_is_stored(tmp_path):
    store.write_matches(tmp_path, [_match("1982-83", "x"), _match("1983-84", "y")])
    assert store.seasons(tmp_path) == ["1982-83", "1983-84"]


def test_a_match_with_no_season_is_refused(tmp_path):
    try:
        store.write_matches(tmp_path, [_match("", "x")])
    except ValueError as exc:
        assert "season" in str(exc)
    else:
        raise AssertionError("a match with no season must not be silently filed")


def test_reading_an_empty_tree_gives_no_matches(tmp_path):
    assert store.read_matches(tmp_path) == []
