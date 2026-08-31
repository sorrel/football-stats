"""Extremes answers wins, losses and the highest-scoring matches at once.

Every result at once, or one measure ranked in full with --by. Either way
the answer comes combined, at home and away — and opponents and
competitions are shown by name, not slug. The highest-scoring section is
whatever is left once the wins and losses above it have had their say.
"""

from click.testing import CliRunner

from football import schema, store
from football.cli import cli
from football.parse.base import blank_row

CLUB = "brighton-hove-albion"


def _m(date, opponent, gf, ga, home=True, **extra):
    row = blank_row(schema.MATCHES)
    row.update({
        "match_id": f"{date}_{CLUB if home else opponent}_"
                    f"{opponent if home else CLUB}",
        "date": date, "season": "1982-83",
        "home_club": CLUB if home else opponent,
        "away_club": opponent if home else CLUB,
        "competition": "division-one", "tier": "1", "status": "played",
        "source": "test",
        "ft_home": str(gf if home else ga), "ft_away": str(ga if home else gf),
    })
    row.update(extra)
    return row


#: Combined: wins v arsenal (home, 5-0) and watford (away, 4-0), a loss to
#: everton (home, 0-3), and a draw with luton-town (away, 2-2). Home and away
#: each get one win and hold the loss or the draw apart from the other.
MATCHES = [
    _m("1982-08-28", "arsenal", 5, 0),
    _m("1982-09-04", "everton", 0, 3),
    _m("1982-09-11", "watford", 4, 0, home=False),
    _m("1982-09-18", "luton-town", 2, 2, home=False),
]


def _seed(data_dir, matches):
    clubs = {s for m in matches for s in (m["home_club"], m["away_club"])}
    store.write_table(data_dir, schema.CLUBS, [
        {"slug": s, "name": n, "former_names": "", "english_league": "true",
         "country": "England", "imported": "true"}
        for s, n in ((CLUB, "Brighton and Hove Albion"), ("arsenal", "Arsenal"),
                     ("everton", "Everton"), ("watford", "Watford"),
                     ("luton-town", "Luton Town"))
        if s in clubs])
    store.write_table(data_dir, schema.COMPETITIONS, [
        {"slug": "division-one", "name": "Division One", "type": "league",
         "tier": "1", "first_season": "", "last_season": ""}])
    store.write_table(data_dir, schema.VENUES, [])
    store.write_matches(data_dir, matches)


def _args(tmp_path):
    return ["--data-dir", str(tmp_path / "data"), "--db", str(tmp_path / "f.db")]


def _run(tmp_path, *extra, matches=MATCHES):
    _seed(tmp_path / "data", matches)
    runner = CliRunner()
    runner.invoke(cli, [*_args(tmp_path), "rebuild"])
    result = runner.invoke(cli, [*_args(tmp_path), "extremes", "--club", CLUB,
                                 *extra])
    assert result.exit_code == 0, result.output
    return result.output


def test_the_bare_command_reports_wins_losses_and_highest_scoring(tmp_path):
    output = _run(tmp_path)
    assert "Wins" in output and "Losses" in output
    assert "Highest scoring" in output


def test_each_result_is_split_combined_home_and_away(tmp_path):
    output = _run(tmp_path)
    for side in ("combined", "home", "away"):
        assert f"Wins — {side}" in output


def test_wins_come_from_each_side_apart_from_the_combined_figure(tmp_path):
    output = _run(tmp_path)
    assert "arsenal" not in output, "opponents are shown by name, not slug"
    assert "Arsenal" in output and "Watford" in output


def test_opponent_and_competition_are_shown_by_name(tmp_path):
    output = _run(tmp_path)
    assert "division-one" not in output
    assert "Division One" in output


def _section(output, caption):
    """The data rows of the table captioned `caption`, as cells."""
    lines = output.splitlines()
    index = lines.index(caption) + 3  # past the caption, header and rule
    rows = []
    while lines[index].strip():
        rows.append([cell.strip() for cell in lines[index].split("|")])
        index += 1
    return rows


def test_highest_scoring_finds_what_the_biggest_win_missed(tmp_path):
    """A 6-5 win is nobody's biggest win by margin, but at eleven goals it
    answers the highest-scoring question anyway, once the 5-0 that beat it
    on margin has already been shown as a win."""
    output = _run(tmp_path, "--top", "1", matches=[
        _m("1982-08-28", "arsenal", 6, 5),
        _m("1982-09-04", "everton", 5, 0),
    ])
    assert _section(output, "Wins — combined")[0][3] == "Everton"
    assert _section(output, "Highest scoring — combined")[0][3] == "Arsenal"


def test_a_side_with_no_such_result_says_so_rather_than_going_quiet(tmp_path):
    output = _run(tmp_path, matches=[_m("1982-08-28", "arsenal", 5, 0)])
    assert "Nothing matches those filters. — Losses — away" in output


def test_no_split_gives_one_table_per_result(tmp_path):
    output = _run(tmp_path, "--no-split")
    assert "— combined" not in output and "— home" not in output
    assert "Wins\n" in output


def test_an_explicit_side_reports_that_side_alone(tmp_path):
    output = _run(tmp_path, "--side", "home")
    assert "— combined" not in output and "— away" not in output
    assert "Wins — home" in output
    assert "Arsenal" in output and "Watford" not in output


def test_by_ranks_a_single_measure_split_by_side(tmp_path):
    output = _run(tmp_path, "--by", "margin")
    assert "Extremes — by margin" in output
    for side in ("combined", "home", "away"):
        assert side in output
    assert "Wins" not in output, "--by shows one measure, not the result sections"
