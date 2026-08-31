import json

from click.testing import CliRunner

from football import schema, store
from football.cli import cli


def _seed(data_dir):
    store.write_table(data_dir, schema.CLUBS, [
        {"slug": "brighton-and-hove-albion", "name": "Brighton and Hove Albion",
         "former_names": "", "english_league": "true", "country": "England"},
        {"slug": "crystal-palace", "name": "Crystal Palace",
         "former_names": "", "english_league": "true", "country": "England"},
    ])
    store.write_table(data_dir, schema.COMPETITIONS, [
        {"slug": "division-one", "name": "Division One", "type": "league", "tier": "1", "first_season": "1888-89",
         "last_season": ""}])
    store.write_table(data_dir, schema.VENUES, [])
    row = {name: "" for name in schema.MATCHES.field_names()}
    row.update({"match_id": "1983-04-02_brighton-and-hove-albion_crystal-palace",
                "date": "1983-04-02", "season": "1982-83",
                "home_club": "brighton-and-hove-albion", "away_club": "crystal-palace",
                "competition": "division-one", "ft_home": "3", "ft_away": "1",
                "status": "played", "source": "test"})
    store.write_matches(data_dir, [row])


def _args(tmp_path):
    return ["--data-dir", str(tmp_path / "data"), "--db", str(tmp_path / "f.db")]


def test_rebuild_reports_what_it_loaded(tmp_path):
    _seed(tmp_path / "data")
    result = CliRunner().invoke(cli, [*_args(tmp_path), "rebuild"])
    assert result.exit_code == 0
    assert "1 match" in result.output


def test_rebuild_counts_are_pluralised_correctly(tmp_path):
    _seed(tmp_path / "data")
    result = CliRunner().invoke(cli, [*_args(tmp_path), "rebuild"])
    assert "1 match," in result.output
    assert "2 clubs" in result.output
    assert "1 competition," in result.output
    assert "0 venues" in result.output


def test_rebuild_fails_with_guidance_not_a_traceback(tmp_path):
    _seed(tmp_path / "data")
    store.write_table(tmp_path / "data", schema.COMPETITIONS, [])
    result = CliRunner().invoke(cli, [*_args(tmp_path), "rebuild"])
    assert result.exit_code != 0
    assert result.exception is None or isinstance(result.exception, SystemExit)
    assert "division-one" in result.output


def test_rebuild_explains_an_unknown_column_rather_than_crashing(tmp_path):
    _seed(tmp_path / "data")
    (tmp_path / "data" / "clubs.csv").write_text("slug,name,nickname\na,A,Gunners\n")
    result = CliRunner().invoke(cli, [*_args(tmp_path), "rebuild"])
    assert result.exit_code != 0
    assert "nickname" in result.output


def test_query_returns_an_aligned_table(tmp_path):
    _seed(tmp_path / "data")
    runner = CliRunner()
    runner.invoke(cli, [*_args(tmp_path), "rebuild"])
    result = runner.invoke(cli, [
        *_args(tmp_path), "query",
        "SELECT club, result FROM club_matches ORDER BY club"])
    assert result.exit_code == 0
    assert "brighton-and-hove-albion" in result.output
    assert "W" in result.output


def test_query_emits_json_when_asked(tmp_path):
    _seed(tmp_path / "data")
    runner = CliRunner()
    runner.invoke(cli, [*_args(tmp_path), "rebuild"])
    result = runner.invoke(cli, [
        *_args(tmp_path), "query", "SELECT club FROM club_matches ORDER BY club",
        "--json"])
    assert json.loads(result.output)[0]["club"] == "brighton-and-hove-albion"


def test_query_rejects_a_statement_that_writes(tmp_path):
    _seed(tmp_path / "data")
    runner = CliRunner()
    runner.invoke(cli, [*_args(tmp_path), "rebuild"])
    result = runner.invoke(cli, [*_args(tmp_path), "query", "DELETE FROM matches"])
    assert result.exit_code != 0
    assert "read-only" in result.output


def test_a_write_disguised_after_a_leading_comment_is_still_rejected(tmp_path):
    _seed(tmp_path / "data")
    runner = CliRunner()
    runner.invoke(cli, [*_args(tmp_path), "rebuild"])
    result = runner.invoke(cli, [
        *_args(tmp_path), "query", "-- harmless\nDROP TABLE matches"])
    assert result.exit_code != 0


def test_query_before_any_rebuild_says_so(tmp_path):
    _seed(tmp_path / "data")
    result = CliRunner().invoke(cli, [*_args(tmp_path), "query", "SELECT 1"])
    assert result.exit_code != 0
    assert "rebuild" in result.output


def test_a_broken_query_explains_itself(tmp_path):
    _seed(tmp_path / "data")
    runner = CliRunner()
    runner.invoke(cli, [*_args(tmp_path), "rebuild"])
    result = runner.invoke(cli, [*_args(tmp_path), "query", "SELECT nope FROM matches"])
    assert result.exit_code != 0
    assert "nope" in result.output


def test_tables_lists_the_columns_available_to_query(tmp_path):
    _seed(tmp_path / "data")
    runner = CliRunner()
    runner.invoke(cli, [*_args(tmp_path), "rebuild"])
    result = runner.invoke(cli, [*_args(tmp_path), "tables"])
    assert result.exit_code == 0
    assert "club_matches" in result.output
    assert "final_result" in result.output
