"""`football clubs --coverage` — a timeline strip per imported club.

Only a club imported as a subject has a record worth drawing a strip for; a
club held only as somebody else's opponent has no season-by-season shape
of its own, so it is left off rather than drawn as a wall of gaps.
"""

from click.testing import CliRunner

from football import schema, store
from football.cli import cli
from football.parse.base import blank_row


def _match(date, home, away, season, competition="division-one"):
    row = blank_row(schema.MATCHES)
    row.update({
        "match_id": f"{date}_{home}_{away}", "date": date, "season": season,
        "home_club": home, "away_club": away, "competition": competition,
        "status": "played", "source": "test", "ft_home": "1", "ft_away": "0",
        "tier": "1" if competition == "division-one" else "",
    })
    return row


def _seed(data_dir):
    store.write_table(data_dir, schema.CLUBS, [
        {"slug": "arsenal", "name": "Arsenal", "former_names": "",
         "english_league": "true", "country": "England", "imported": "true"},
        {"slug": "watford", "name": "Watford", "former_names": "",
         "english_league": "true", "country": "England", "imported": ""},
    ])
    store.write_table(data_dir, schema.COMPETITIONS, [
        {"slug": "division-one", "name": "Division One", "type": "league",
         "tier": "1", "first_season": "", "last_season": ""}])
    store.write_table(data_dir, schema.VENUES, [])
    store.write_matches(data_dir, [
        _match("1983-04-02", "arsenal", "watford", "1982-83")])


def _run(tmp_path, args):
    _seed(tmp_path / "data")
    runner = CliRunner()
    base = ["--data-dir", str(tmp_path / "data"), "--db", str(tmp_path / "f.db")]
    runner.invoke(cli, [*base, "rebuild"])
    return runner.invoke(cli, [*base, *args])


def test_only_imported_clubs_get_a_strip(tmp_path):
    result = _run(tmp_path, ["clubs", "--coverage"])

    assert result.exit_code == 0
    assert "Arsenal" in result.output
    assert "Watford" not in result.output


def test_coverage_without_a_club_shows_the_same_grid(tmp_path):
    """`football coverage` on its own has no one club's record to report,
    so it answers the question it can: every imported club at once."""
    result = _run(tmp_path, ["coverage"])

    assert result.exit_code == 0
    assert "Arsenal" in result.output
    assert "Watford" not in result.output
    assert "held in full" in result.output


def test_coverage_with_a_filter_but_no_club_asks_for_one(tmp_path):
    """A filter narrows one club's record; without --club there is no
    record to narrow, so it is refused rather than silently ignored."""
    result = _run(tmp_path, ["coverage", "--tier", "1"])

    assert result.exit_code != 0
    assert "Which club?" in result.output


def test_the_legend_explains_the_glyphs(tmp_path):
    result = _run(tmp_path, ["clubs", "--coverage"])

    assert "held in full" in result.output


def test_search_and_coverage_combine(tmp_path):
    result = _run(tmp_path, ["clubs", "arsenal", "--coverage"])

    assert result.exit_code == 0
    assert "Arsenal" in result.output


def test_nothing_imported_says_so(tmp_path):
    result = _run(tmp_path, ["clubs", "watford", "--coverage"])

    assert result.exit_code == 0
    assert "None of these have been imported yet" in result.output


def _seed_two_imported(data_dir):
    """A short name and a long one, with different first seasons, so a
    fixed name column and a fixed bar start are two different claims."""
    store.write_table(data_dir, schema.CLUBS, [
        {"slug": "afc", "name": "AFC", "former_names": "",
         "english_league": "true", "country": "England", "imported": "true"},
        {"slug": "a-much-longer-club-name", "name": "A Much Longer Club Name",
         "former_names": "", "english_league": "true",
         "country": "England", "imported": "true"},
    ])
    store.write_table(data_dir, schema.COMPETITIONS, [
        {"slug": "division-one", "name": "Division One", "type": "league",
         "tier": "1", "first_season": "", "last_season": ""}])
    store.write_table(data_dir, schema.VENUES, [])
    store.write_matches(data_dir, [
        _match("1990-08-11", "afc", "a-much-longer-club-name", "1990-91"),
        _match("2000-08-12", "a-much-longer-club-name", "afc", "2000-01"),
    ])


def test_bars_start_in_the_same_column_regardless_of_name_length(tmp_path):
    _seed_two_imported(tmp_path / "data")
    runner = CliRunner()
    base = ["--data-dir", str(tmp_path / "data"), "--db", str(tmp_path / "f.db")]
    runner.invoke(cli, [*base, "rebuild"])
    result = runner.invoke(cli, [*base, "clubs", "--coverage"])

    lines = [line for line in result.output.splitlines()
             if line.startswith("AFC") or line.startswith("A Much")]
    assert len(lines) == 2
    bar_at = [line.index("199") if "199" in line else line.index("200")
             for line in lines]
    assert bar_at[0] == bar_at[1]


def _seed_different_lengths(data_dir):
    """Two clubs whose bars are different lengths, so the end season only
    lines up if the shorter bar is padded out to the longer one's width."""
    store.write_table(data_dir, schema.CLUBS, [
        {"slug": "short", "name": "Short", "former_names": "",
         "english_league": "true", "country": "England", "imported": "true"},
        {"slug": "long", "name": "Long", "former_names": "",
         "english_league": "true", "country": "England", "imported": "true"},
    ])
    store.write_table(data_dir, schema.COMPETITIONS, [
        {"slug": "division-one", "name": "Division One", "type": "league",
         "tier": "1", "first_season": "", "last_season": ""}])
    store.write_table(data_dir, schema.VENUES, [])
    store.write_matches(data_dir, [
        _match("1990-08-11", "short", "short", "1990-91"),
        _match("1990-08-11", "long", "long", "1990-91"),
        _match("2010-08-14", "long", "long", "2010-11"),
    ])


def test_end_seasons_line_up_even_when_bars_differ_in_length(tmp_path):
    _seed_different_lengths(tmp_path / "data")
    runner = CliRunner()
    base = ["--data-dir", str(tmp_path / "data"), "--db", str(tmp_path / "f.db")]
    runner.invoke(cli, [*base, "rebuild"])
    result = runner.invoke(cli, [*base, "clubs", "--coverage"])

    lines = [line for line in result.output.splitlines()
             if line.startswith("Short") or line.startswith("Long")]
    assert len(lines) == 2
    end_at = [line.rindex("199") if line.startswith("Short")
             else line.rindex("201") for line in lines]
    assert end_at[0] == end_at[1]


def _seed_shifted_start(data_dir):
    """Two clubs of one season each, a decade apart — nothing in common
    except the shared axis the grid is supposed to draw them against."""
    store.write_table(data_dir, schema.CLUBS, [
        {"slug": "early", "name": "Early", "former_names": "",
         "english_league": "true", "country": "England", "imported": "true"},
        {"slug": "later", "name": "Later", "former_names": "",
         "english_league": "true", "country": "England", "imported": "true"},
    ])
    store.write_table(data_dir, schema.COMPETITIONS, [
        {"slug": "division-one", "name": "Division One", "type": "league",
         "tier": "1", "first_season": "", "last_season": ""}])
    store.write_table(data_dir, schema.VENUES, [])
    store.write_matches(data_dir, [
        _match("1980-08-16", "early", "early", "1980-81"),
        _match("1990-08-18", "later", "later", "1990-91"),
    ])


def test_a_shared_season_sits_in_the_same_column_on_every_row(tmp_path):
    """The point of the grid: a column means one season, whoever's row it
    is in — not "this many seasons into this club's own record"."""
    _seed_shifted_start(tmp_path / "data")
    runner = CliRunner()
    base = ["--data-dir", str(tmp_path / "data"), "--db", str(tmp_path / "f.db")]
    runner.invoke(cli, [*base, "rebuild"])
    result = runner.invoke(cli, [*base, "clubs", "--coverage"])

    lines = {line.split()[0]: line for line in result.output.splitlines()
             if line.startswith("Early") or line.startswith("Later")}
    glyphs = "█▒·×"
    early_at = next(i for i, ch in enumerate(lines["Early"]) if ch in glyphs)
    later_at = next(i for i, ch in enumerate(lines["Later"]) if ch in glyphs)
    # Later's one season is a decade after Early's; the same decade of
    # blank padding must separate their glyphs for a column to mean a
    # season rather than an offset into each club's own record.
    assert later_at - early_at == 10
