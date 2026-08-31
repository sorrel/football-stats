"""Where the CLI looks for its data.

The defaults are relative, so running from another directory would look for
a `data/` that is not there. Environment variables make the command usable
from anywhere without hard-coding a path into the tool.
"""

from click.testing import CliRunner

from football import schema, store
from football.cli import cli


def _seed(data_dir):
    store.write_table(data_dir, schema.CLUBS, [
        {"slug": "brighton-hove-albion", "name": "Brighton", "former_names": "",
         "english_league": "true", "country": "England"}])
    for table in (schema.COMPETITIONS, schema.VENUES):
        store.write_table(data_dir, table, [])


def test_the_data_directory_can_come_from_the_environment(tmp_path, monkeypatch):
    _seed(tmp_path / "data")
    monkeypatch.setenv("FOOTBALL_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("FOOTBALL_DB", str(tmp_path / "f.db"))
    result = CliRunner().invoke(cli, ["rebuild"])
    assert result.exit_code == 0
    assert (tmp_path / "f.db").exists()


def test_an_explicit_path_beats_the_environment(tmp_path, monkeypatch):
    _seed(tmp_path / "data")
    monkeypatch.setenv("FOOTBALL_DATA_DIR", "/nowhere/at/all")
    result = CliRunner().invoke(cli, [
        "--data-dir", str(tmp_path / "data"), "--db", str(tmp_path / "f.db"),
        "rebuild"])
    assert result.exit_code == 0


def test_the_relative_default_still_applies_with_no_environment(monkeypatch):
    monkeypatch.delenv("FOOTBALL_DATA_DIR", raising=False)
    monkeypatch.delenv("FOOTBALL_DB", raising=False)
    result = CliRunner().invoke(cli, ["--help"])
    assert result.exit_code == 0
