"""Adding a field must be a one-line schema change plus a re-parse.

If these tests fail, the schema has stopped being the single source of truth
and the extension workflow in README.md is no longer accurate.
"""

from football import db, schema, store


def test_the_new_field_is_declared_once_in_the_schema():
    assert "abandoned_reason" in schema.MATCHES.field_names()


def test_existing_files_written_before_the_field_existed_still_load(tmp_path):
    """The committed files predate the new column; they must read as empty."""
    names = [n for n in schema.MATCHES.field_names() if n != "abandoned_reason"]
    header = ",".join(names)
    values = ["" for _ in names]
    values[names.index("match_id")] = "1983-05-21_a_b"
    matches_dir = tmp_path / "matches"
    matches_dir.mkdir(parents=True)
    (matches_dir / "1982-83.csv").write_text(f"{header}\n{','.join(values)}\n")
    rows = store.read_matches(tmp_path)
    assert rows[0]["abandoned_reason"] == ""
    assert rows[0]["match_id"] == "1983-05-21_a_b"


def test_the_database_picks_up_the_new_column_with_no_db_code_change(tmp_path):
    for table in (schema.CLUBS, schema.COMPETITIONS, schema.VENUES):
        store.write_table(tmp_path, table, [])
    conn = db.build(tmp_path, tmp_path / "f.db")
    columns = {row[1] for row in conn.execute("PRAGMA table_info(matches)")}
    assert "abandoned_reason" in columns
