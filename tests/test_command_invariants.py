"""Invariants every analysis command must hold.

These are behavioural, not structural: a command added later that forgot to
resolve its club would accept a typo and report an empty record as though it
were an answer. This fails instead.
"""

import pytest
from click.testing import CliRunner

from football import schema, store
from football.cli import cli
from football.parse.base import blank_row

#: Every command that takes --club and reports on matches.
ANALYSIS_COMMANDS = [
    ["record"],
    ["h2h", "watford"],
    ["runs"],
    ["extremes"],
    ["seasons"],
]


def _seed(data_dir):
    store.write_table(data_dir, schema.CLUBS, [
        {"slug": s, "name": s.title(), "former_names": "",
         "english_league": "true", "country": "England", "imported": "true"}
        for s in ("arsenal", "watford")])
    store.write_table(data_dir, schema.COMPETITIONS, [
        {"slug": "division-one", "name": "Division One", "type": "league",
         "tier": "", "first_season": "", "last_season": ""}])
    store.write_table(data_dir, schema.VENUES, [])
    row = blank_row(schema.MATCHES)
    row.update({"match_id": "m1", "date": "1983-04-02", "season": "1982-83",
                "home_club": "arsenal", "away_club": "watford",
                "competition": "division-one", "ft_home": "2", "ft_away": "1",
                "status": "played", "source": "test"})
    store.write_matches(data_dir, [row])


def _invoke(tmp_path, command, club):
    _seed(tmp_path / "data")
    runner = CliRunner()
    args = ["--data-dir", str(tmp_path / "data"), "--db", str(tmp_path / "f.db")]
    runner.invoke(cli, [*args, "rebuild"])
    return runner.invoke(cli, [*args, *command, "--club", club])


@pytest.mark.parametrize("command", ANALYSIS_COMMANDS,
                         ids=lambda c: c[0])
def test_every_command_rejects_an_unknown_club(tmp_path, command):
    """A typo must not read as a club with nothing to report."""
    result = _invoke(tmp_path, command, "arsnal-typo")
    assert result.exit_code != 0
    assert "not a club" in result.output


@pytest.mark.parametrize("command", ANALYSIS_COMMANDS, ids=lambda c: c[0])
def test_every_command_accepts_a_partial_name(tmp_path, command):
    """Fuzzy resolution is shared, so every command gets it."""
    result = _invoke(tmp_path, command, "arse")
    assert result.exit_code == 0


@pytest.mark.parametrize("command", ANALYSIS_COMMANDS, ids=lambda c: c[0])
def test_every_command_names_the_club_it_answered_about(tmp_path, command):
    result = _invoke(tmp_path, command, "arsenal")
    assert "Arsenal" in result.output
