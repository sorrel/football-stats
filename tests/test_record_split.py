"""`record` splits home, away and neutral, then totals them."""

from click.testing import CliRunner

from football import schema, store
from football.cli import cli
from football.parse.base import blank_row

US, THEM = "brighton-hove-albion", "watford"


def _match(date, gf, ga, home=True, neutral=""):
    row = blank_row(schema.MATCHES)
    row.update({
        "match_id": f"{date}_{US if home else THEM}_{THEM if home else US}",
        "date": date, "season": "1982-83", "competition": "division-one",
        "home_club": US if home else THEM, "away_club": THEM if home else US,
        "tier": "1", "neutral": neutral, "status": "played", "source": "test",
        "ft_home": str(gf if home else ga), "ft_away": str(ga if home else gf)})
    return row


def _run(tmp_path, matches, extra=()):
    data = tmp_path / "data"
    store.write_table(data, schema.CLUBS, [
        {"slug": s, "name": s, "former_names": "", "english_league": "true",
         "country": "England"} for s in (US, THEM)])
    store.write_table(data, schema.COMPETITIONS, [
        {"slug": "division-one", "name": "Division One", "type": "league",
         "tier": "", "first_season": "", "last_season": ""}])
    store.write_table(data, schema.VENUES, [])
    store.write_matches(data, matches)
    args = ["--data-dir", str(data), "--db", str(tmp_path / "f.db")]
    runner = CliRunner()
    runner.invoke(cli, [*args, "rebuild"])
    return runner.invoke(cli, [*args, "record", "--club", US, *extra])


def _row(output, label):
    for line in output.splitlines():
        if line.startswith(label):
            return [cell.strip() for cell in line.split("|")]
    raise AssertionError(f"no {label!r} row in:\n{output}")


def test_home_and_away_appear_as_separate_lines(tmp_path):
    result = _run(tmp_path, [_match("1983-01-01", 3, 1), _match("1983-02-01", 0, 2, home=False)])
    assert result.exit_code == 0
    assert _row(result.output, "home")[1] == "1"
    assert _row(result.output, "away")[1] == "1"


def test_the_total_line_sums_them(tmp_path):
    result = _run(tmp_path, [
        _match("1983-01-01", 3, 1), _match("1983-01-08", 2, 0),
        _match("1983-02-01", 0, 2, home=False)])
    total = _row(result.output, "total")
    assert total[1] == "3"
    assert total[2] == "2"  # won


def test_the_total_is_last(tmp_path):
    result = _run(tmp_path, [_match("1983-01-01", 3, 1), _match("1983-02-01", 0, 2, home=False)])
    labels = [l.split("|")[0].strip() for l in result.output.splitlines()
              if l.split("|")[0].strip() in {"home", "away", "neutral", "total"}]
    assert labels[-1] == "total"


def test_a_neutral_ground_is_its_own_line(tmp_path):
    result = _run(tmp_path, [
        _match("1983-01-01", 3, 1),
        _match("1983-05-21", 2, 2, home=False, neutral="true")])
    assert _row(result.output, "neutral")[1] == "1"


def test_no_neutral_line_when_there_were_none(tmp_path):
    result = _run(tmp_path, [_match("1983-01-01", 3, 1)])
    assert "neutral" not in result.output


def test_goals_split_by_side_too(tmp_path):
    result = _run(tmp_path, [_match("1983-01-01", 3, 1), _match("1983-02-01", 0, 2, home=False)])
    assert _row(result.output, "home")[5] == "3"   # goals for
    assert _row(result.output, "away")[5] == "0"


def test_the_split_respects_the_filters(tmp_path):
    result = _run(tmp_path, [_match("1983-01-01", 3, 1), _match("1983-02-01", 0, 2, home=False)],
                  extra=("--side", "home"))
    assert "away" not in result.output
