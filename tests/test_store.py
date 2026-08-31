import pytest

from football import schema, store


def test_write_then_read_round_trips(tmp_path):
    rows = [{"slug": "brighton-and-hove-albion", "name": "Brighton and Hove Albion",
             "former_names": "", "english_league": "true", "country": "England", "imported": ""}]
    store.write_table(tmp_path, schema.CLUBS, rows)
    assert store.read_table(tmp_path, schema.CLUBS) == rows


def test_rows_are_written_sorted_by_key_for_stable_diffs(tmp_path):
    rows = [
        {"slug": "watford", "name": "Watford", "former_names": "",
         "english_league": "true", "country": "England"},
        {"slug": "arsenal", "name": "Arsenal", "former_names": "",
         "english_league": "true", "country": "England"},
    ]
    store.write_table(tmp_path, schema.CLUBS, rows)
    written = (tmp_path / "clubs.csv").read_text().splitlines()
    assert written[1].startswith("arsenal")
    assert written[2].startswith("watford")


def test_writing_the_same_rows_twice_produces_an_identical_file(tmp_path):
    rows = [{"slug": "arsenal", "name": "Arsenal", "former_names": "",
             "english_league": "true", "country": "England"}]
    store.write_table(tmp_path, schema.CLUBS, rows)
    first = (tmp_path / "clubs.csv").read_bytes()
    store.write_table(tmp_path, schema.CLUBS, list(reversed(rows)))
    assert (tmp_path / "clubs.csv").read_bytes() == first


def test_a_missing_file_reads_as_no_rows(tmp_path):
    assert store.read_table(tmp_path, schema.CLUBS) == []


def test_a_newly_added_column_reads_as_empty_in_an_older_file(tmp_path):
    """Forward compatibility: the file predates a field added to the schema."""
    (tmp_path / "clubs.csv").write_text("slug,name\narsenal,Arsenal\n")
    rows = store.read_table(tmp_path, schema.CLUBS)
    assert rows[0]["country"] == ""
    assert rows[0]["name"] == "Arsenal"


def test_an_unknown_column_is_an_error_not_a_silent_drop(tmp_path):
    (tmp_path / "clubs.csv").write_text("slug,name,nickname\narsenal,Arsenal,Gunners\n")
    with pytest.raises(store.UnknownColumnError, match="nickname"):
        store.read_table(tmp_path, schema.CLUBS)


def test_upsert_replaces_an_existing_row_rather_than_duplicating_it():
    existing = [{"slug": "arsenal", "name": "Arsenal"}]
    incoming = [{"slug": "arsenal", "name": "Arsenal FC"},
                {"slug": "watford", "name": "Watford"}]
    result = store.upsert(existing, incoming, key="slug")
    assert len(result) == 2
    assert {r["slug"]: r["name"] for r in result} == {
        "arsenal": "Arsenal FC", "watford": "Watford"}
