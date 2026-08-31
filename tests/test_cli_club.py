"""The club must be stated. There is no default.

Once a second club exists, defaulting to Brighton would answer a question
about one club with another's record — wrong, but indistinguishable from
right.
"""

from click.testing import CliRunner

from football import schema, store
from football.cli import cli
from football.parse.base import blank_row


def _seed(data_dir):
    store.write_table(data_dir, schema.CLUBS, [
        {"slug": s, "name": n, "former_names": "", "english_league": "true",
         "country": "England"}
        for s, n in (("brighton-hove-albion", "Brighton and Hove Albion"),
                     ("crystal-palace", "Crystal Palace"))])
    store.write_table(data_dir, schema.COMPETITIONS, [
        {"slug": "division-one", "name": "Division One", "type": "league",
         "tier": "", "first_season": "", "last_season": ""}])
    store.write_table(data_dir, schema.VENUES, [])
    row = blank_row(schema.MATCHES)
    row.update({"match_id": "1983-04-02_brighton-hove-albion_crystal-palace",
                "date": "1983-04-02", "season": "1982-83",
                "home_club": "brighton-hove-albion", "away_club": "crystal-palace",
                "competition": "division-one", "tier": "1", "ft_home": "3",
                "ft_away": "1", "status": "played", "source": "test"})
    store.write_matches(data_dir, [row])


def _args(tmp_path):
    return ["--data-dir", str(tmp_path / "data"), "--db", str(tmp_path / "f.db")]


def _built(tmp_path):
    _seed(tmp_path / "data")
    runner = CliRunner()
    runner.invoke(cli, [*_args(tmp_path), "rebuild"])
    return runner


def test_omitting_the_club_is_an_error_not_a_silent_default(tmp_path):
    runner = _built(tmp_path)
    result = runner.invoke(cli, [*_args(tmp_path), "record"])
    assert result.exit_code != 0
    assert "--club" in result.output


def test_the_error_names_the_environment_variable(tmp_path):
    runner = _built(tmp_path)
    result = runner.invoke(cli, [*_args(tmp_path), "record"])
    assert "FOOTBALL_CLUB" in result.output


def test_the_environment_variable_supplies_the_club(tmp_path, monkeypatch):
    runner = _built(tmp_path)
    monkeypatch.setenv("FOOTBALL_CLUB", "brighton-hove-albion")
    result = runner.invoke(cli, [*_args(tmp_path), "record"])
    assert result.exit_code == 0
    assert "brighton" in result.output.lower()


def test_an_explicit_club_beats_the_environment(tmp_path, monkeypatch):
    runner = _built(tmp_path)
    monkeypatch.setenv("FOOTBALL_CLUB", "crystal-palace")
    result = runner.invoke(cli, [
        *_args(tmp_path), "record", "--club", "brighton-hove-albion"])
    assert "Brighton" in result.output


def test_an_unknown_club_is_rejected_rather_than_returning_nothing(tmp_path):
    """A typo must not look like a club with no matches."""
    runner = _built(tmp_path)
    result = runner.invoke(cli, [*_args(tmp_path), "record", "--club", "brihgton"])
    assert result.exit_code != 0
    assert "brihgton" in result.output
    assert "not a club" in result.output.lower() or "unknown" in result.output.lower()


def test_a_partial_name_resolves_without_the_full_slug(tmp_path):
    """"brighton" is unambiguous here, so it needs no chooser."""
    runner = _built(tmp_path)
    result = runner.invoke(cli, [*_args(tmp_path), "record", "--club", "brighton"])
    assert result.exit_code == 0
    assert "Brighton and Hove Albion" in result.output


def test_a_real_club_with_no_matches_is_not_an_error(tmp_path):
    """Distinct from a typo: the club exists, it simply has no matches here."""
    runner = _built(tmp_path)
    result = runner.invoke(cli, [
        *_args(tmp_path), "record", "--club", "crystal-palace",
        "--competition", "fa-cup"])
    assert result.exit_code == 0
    assert "No matches" in result.output


def test_an_ambiguous_name_lists_the_options(tmp_path):
    """"Albion" is several clubs; the user picks rather than us guessing."""
    _seed(tmp_path / "data")
    runner = CliRunner()
    runner.invoke(cli, [*_args(tmp_path), "rebuild"])
    result = runner.invoke(cli, [*_args(tmp_path), "record", "--club", "a"])
    assert result.exit_code != 0
    assert "1." in result.output and "2." in result.output


def test_a_non_interactive_run_never_waits_for_a_prompt(tmp_path):
    """A script must fail with the options, not hang forever."""
    _seed(tmp_path / "data")
    runner = CliRunner()
    runner.invoke(cli, [*_args(tmp_path), "rebuild"])
    result = runner.invoke(cli, [*_args(tmp_path), "record", "--club", "a"],
                           input="")
    assert result.exit_code != 0
    assert "exactly" in result.output


def test_a_partial_name_that_is_unique_just_works(tmp_path):
    _seed(tmp_path / "data")
    runner = CliRunner()
    runner.invoke(cli, [*_args(tmp_path), "rebuild"])
    result = runner.invoke(cli, [*_args(tmp_path), "record", "--club", "palace"])
    assert result.exit_code == 0
    assert "Crystal Palace" in result.output
