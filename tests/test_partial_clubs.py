"""A club held only as an opponent must not look complete.

Its handful of meetings with the clubs we do hold would otherwise be
formatted exactly like a full record — wrong in the way that is hardest to
notice, because it looks right.
"""

from click.testing import CliRunner

from football import schema, store
from football.cli import cli
from football.parse.base import blank_row


def _seed(data_dir):
    store.write_table(data_dir, schema.CLUBS, [
        {"slug": "arsenal", "name": "Arsenal", "former_names": "",
         "english_league": "true", "country": "England", "imported": "true"},
        {"slug": "accrington", "name": "Accrington", "former_names": "",
         "english_league": "true", "country": "England", "imported": ""}])
    store.write_table(data_dir, schema.COMPETITIONS, [
        {"slug": "division-one", "name": "Division One", "type": "league",
         "tier": "", "first_season": "", "last_season": ""}])
    store.write_table(data_dir, schema.VENUES, [])
    row = blank_row(schema.MATCHES)
    row.update({"match_id": "m1", "date": "1920-01-01", "season": "1919-20",
                "home_club": "arsenal", "away_club": "accrington",
                "competition": "division-one", "ft_home": "2", "ft_away": "1",
                "status": "played", "source": "test"})
    store.write_matches(data_dir, [row])


def _run(tmp_path, club):
    _seed(tmp_path / "data")
    runner = CliRunner()
    args = ["--data-dir", str(tmp_path / "data"), "--db", str(tmp_path / "f.db")]
    runner.invoke(cli, [*args, "rebuild"])
    return runner.invoke(cli, [*args, "record", "--club", club])


def test_a_club_held_only_as_an_opponent_is_flagged(tmp_path):
    result = _run(tmp_path, "accrington")
    assert result.exit_code == 0
    assert "has not been imported" in result.output


def test_the_warning_says_how_to_fix_it(tmp_path):
    result = _run(tmp_path, "accrington")
    assert "football import engsoccerdata --club accrington" in result.output


def test_an_imported_club_is_not_flagged(tmp_path):
    result = _run(tmp_path, "arsenal")
    assert "has not been imported" not in result.output


def test_the_figures_are_still_shown(tmp_path):
    """Flagged, not withheld: the matches we hold are real."""
    result = _run(tmp_path, "accrington")
    assert "played" in result.output
    assert any(line.startswith("away") for line in result.output.splitlines())
