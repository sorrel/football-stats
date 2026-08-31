"""Importing into an empty database.

The club must be allowed not to exist yet: it is often absent precisely
because this is the import that will add it. Refusing would mean nothing
could ever be imported into an empty database — and adding a second club
would be impossible too.
"""

import click
import pytest

from football.cli_import import resolve_for_import
from football.sources.builders import _name_in_source


def _strict(conn, club):
    """Stands in for the analysis resolver, which refuses unknown clubs."""
    if club != "known-club":
        raise click.ClickException(f"{club!r} is not a club in this database.")
    return club


def test_a_known_club_resolves_as_usual():
    assert resolve_for_import(_strict, None, "known-club") == "known-club"


def test_an_unknown_club_is_accepted_for_import():
    assert resolve_for_import(_strict, None, "rochdale") == "rochdale"


def test_no_club_at_all_is_still_refused():
    with pytest.raises(click.ClickException, match="Which club"):
        resolve_for_import(_strict, None, None)


def test_the_club_name_is_found_in_the_source_not_the_database():
    """Otherwise a club we do not hold could never be imported."""
    records = [{"home": "Brighton & Hove Albion", "visitor": "Arsenal"}]
    assert _name_in_source(records, "brighton-hove-albion") == (
        "Brighton & Hove Albion")


def test_a_club_absent_from_the_source_is_reported_not_invented():
    records = [{"home": "Arsenal", "visitor": "Chelsea"}]
    assert _name_in_source(records, "rochdale") == ""


def test_the_name_is_found_whichever_side_the_club_played():
    records = [{"home": "Arsenal", "visitor": "Rochdale"}]
    assert _name_in_source(records, "rochdale") == "Rochdale"


def test_importing_works_even_when_the_database_will_not_build(tmp_path):
    """An import is often exactly what repairs an inconsistent database."""
    from click.testing import CliRunner

    from football import schema, store
    from football.cli import cli
    from football.parse.base import blank_row

    data = tmp_path / "data"
    store.write_table(data, schema.CLUBS, [
        {"slug": "arsenal", "name": "Arsenal", "former_names": "",
         "english_league": "true", "country": "England"}])
    store.write_table(data, schema.COMPETITIONS, [])
    store.write_table(data, schema.VENUES, [])
    # A match naming a competition that does not exist: the build will refuse.
    row = blank_row(schema.MATCHES)
    row.update({"match_id": "m1", "date": "2020-01-01", "season": "2019-20",
                "home_club": "arsenal", "away_club": "arsenal",
                "competition": "champions-league", "status": "played",
                "source": "test"})
    store.write_matches(data, [row])

    result = CliRunner().invoke(cli, [
        "--data-dir", str(data), "--db", str(tmp_path / "f.db"),
        "--cache-dir", str(tmp_path / "cache"),
        "import", "engsoccerdata", "--club", "arsenal", "--dry-run"])
    # It must reach the source rather than dying on the broken database.
    assert "does not currently build" in result.output
    assert "No pages cached" in result.output or result.exit_code == 0
