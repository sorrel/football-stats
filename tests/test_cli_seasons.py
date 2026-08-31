from click.testing import CliRunner

from football import schema, store
from football.cli import cli
from football.parse.base import blank_row


def _match(date, season, competition, opponent, gf, ga, tier="", round_=""):
    row = blank_row(schema.MATCHES)
    us = "brighton-hove-albion"
    row.update({"match_id": f"{date}_{us}_{opponent}", "date": date,
                "season": season, "competition": competition,
                "home_club": us, "away_club": opponent, "tier": tier,
                "round": round_, "status": "played", "source": "test",
                "ft_home": str(gf), "ft_away": str(ga)})
    return row


def _competition(slug, name, type_):
    return {"slug": slug, "name": name, "type": type_, "tier": "",
            "first_season": "", "last_season": ""}


def _seed(data_dir):
    store.write_table(data_dir, schema.CLUBS, [
        {"slug": s, "name": s, "former_names": "", "english_league": "true",
         "country": "England"}
        for s in ("brighton-hove-albion", "watford", "millwall")])
    store.write_table(data_dir, schema.COMPETITIONS, [
        _competition("division-two", "Division Two", "league"),
        _competition("division-one", "Division One", "league"),
        _competition("division-two-play-offs", "Division Two Play-offs", "play-off")])
    store.write_table(data_dir, schema.VENUES, [])
    store.write_matches(data_dir, [
        _match("1979-04-01", "1978-79", "division-two", "watford", 2, 0, tier="2"),
        _match("1979-04-08", "1978-79", "division-two-play-offs", "millwall",
               1, 0, tier="2", round_="Semi-final"),
        _match("1980-04-01", "1979-80", "division-one", "watford", 1, 1, tier="1"),
    ])
    store.write_seasons(data_dir, [
        {**{n: "" for n in schema.SEASONS.field_names()},
         "season_id": "1978-79_brighton-hove-albion_division-two",
         "club": "brighton-hove-albion", "season": "1978-79",
         "competition": "division-two", "tier": "2", "position": "2",
         "points": "56", "source": "test"}])


def _args(tmp_path):
    return ["--data-dir", str(tmp_path / "data"), "--db", str(tmp_path / "f.db")]


def test_seasons_lists_position_and_outcome(tmp_path):
    _seed(tmp_path / "data")
    runner = CliRunner()
    runner.invoke(cli, [*_args(tmp_path), "rebuild"])
    result = runner.invoke(cli, [*_args(tmp_path), "seasons", "--club", "brighton-hove-albion"])
    assert result.exit_code == 0
    assert "1978-79" in result.output
    assert "promoted-via-play-offs" in result.output


def test_seasons_shows_the_play_off_record_separately(tmp_path):
    """Play-offs are an addendum to a league season, not part of it."""
    _seed(tmp_path / "data")
    runner = CliRunner()
    runner.invoke(cli, [*_args(tmp_path), "rebuild"])
    result = runner.invoke(cli, [*_args(tmp_path), "seasons", "--club", "brighton-hove-albion"])
    assert "play-off" in result.output.lower()


def test_record_warns_when_play_off_matches_are_included(tmp_path):
    _seed(tmp_path / "data")
    runner = CliRunner()
    runner.invoke(cli, [*_args(tmp_path), "rebuild"])
    result = runner.invoke(cli, [*_args(tmp_path), "record", "--tier", "2", "--club", "brighton-hove-albion"])
    assert "play-off" in result.output.lower()
    assert "--type league" in result.output


def test_record_does_not_warn_when_no_play_offs_are_involved(tmp_path):
    _seed(tmp_path / "data")
    runner = CliRunner()
    runner.invoke(cli, [*_args(tmp_path), "rebuild"])
    result = runner.invoke(cli, [
        *_args(tmp_path), "record", "--tier", "2", "--type", "league",
        "--club", "brighton-hove-albion"])
    assert "addendum" not in result.output


def test_seasons_before_any_rebuild_says_so(tmp_path):
    _seed(tmp_path / "data")
    result = CliRunner().invoke(cli, [*_args(tmp_path), "seasons", "--club", "brighton-hove-albion"])
    assert result.exit_code != 0 and "rebuild" in result.output
