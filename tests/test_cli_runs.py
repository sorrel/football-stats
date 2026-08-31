"""The runs command answers every run question at once.

One command, no flags: the longest unbeaten, winning, drawing and losing
sequences, the droughts without a win and without a goal, and the clean
sheets — each of them combined, at home, and away. `--of` is for drilling
into one of them, not for getting an answer at all.
"""

from click.testing import CliRunner

from football import schema, store
from football.cli import cli
from football.parse.base import blank_row

CLUB = "brighton-hove-albion"

_RUN_LABELS = ("unbeaten", "wins", "draws", "losses", "without a win",
               "without a goal", "clean sheets")


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


#: Combined: unbeaten 4, wins 3, draws 1, losses 1, without a win 2,
#: without a goal 2, clean sheets 4. Home and away differ throughout.
MATCHES = [
    _m("1982-08-28", "arsenal", 1, 1),
    _m("1982-09-04", "watford", 0, 1, home=False),
    _m("1982-09-11", "everton", 2, 0),
    _m("1982-09-18", "ipswich-town", 3, 0, home=False),
    _m("1982-09-25", "luton-town", 1, 0),
    _m("1982-10-02", "stoke-city", 0, 0, home=False),
    _m("1982-10-09", "aston-villa", 0, 2),
]


def _seed(data_dir, matches):
    clubs = {s for m in matches for s in (m["home_club"], m["away_club"])}
    store.write_table(data_dir, schema.CLUBS, [
        {"slug": s, "name": s, "former_names": "", "english_league": "true",
         "country": "England", "imported": "true"} for s in sorted(clubs)])
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
    result = runner.invoke(cli, [*_args(tmp_path), "runs", "--club", CLUB,
                                 *extra])
    assert result.exit_code == 0, result.output
    return result.output


def _row(output, label):
    """The cells of the summary row for `label`."""
    for line in output.splitlines():
        cells = [cell.strip() for cell in line.split("|")]
        if cells[0] == label:
            return cells
    raise AssertionError(f"no {label!r} row in:\n{output}")


def _lengths(output, label):
    """Just the run lengths from a summary row, without their seasons."""
    return [cell.split(" ")[0] for cell in _row(output, label)[1:]]


def _listing(output, side="combined"):
    """The rows of one side's detail table, as cells.

    `side=None` takes every data row, for the single table --no-split gives.
    """
    rows, inside = [], side is None
    for line in output.splitlines():
        if side is not None and line and not line[0].isspace():
            if " — " in line:
                inside = line.strip().endswith(f"— {side}")
        cells = [cell.strip() for cell in line.split("|")]
        if inside and len(cells) > 1 and cells[0].isdigit():
            rows.append(cells)
    return rows


def test_the_bare_command_reports_every_kind_of_run(tmp_path):
    output = _run(tmp_path)
    for label in ("unbeaten", "wins", "draws", "losses", "without a win",
                  "without a goal", "clean sheets"):
        _row(output, label)


def test_the_summary_splits_each_run_home_and_away(tmp_path):
    output = _run(tmp_path)
    assert "combined" in output and "home" in output and "away" in output


def test_the_summary_figures_are_the_longest_of_each_kind(tmp_path):
    output = _run(tmp_path)
    assert _lengths(output, "unbeaten")[0] == "4"
    assert _lengths(output, "wins")[0] == "3"
    assert _row(output, "unbeaten")[1] == "4 (1982-83)", "and the season it fell in"


def test_home_and_away_are_counted_apart_from_the_combined_figure(tmp_path):
    """Three unbeaten at home and two away, but four when they are one run."""
    assert _lengths(_run(tmp_path), "unbeaten") == ["4", "3", "2"]


def test_an_explicit_side_reports_that_side_alone(tmp_path):
    output = _run(tmp_path, "--side", "away")
    assert "combined" not in output
    assert _lengths(output, "unbeaten") == ["2"]


def test_a_kind_that_never_happened_says_so_rather_than_showing_nothing(tmp_path):
    output = _run(tmp_path, matches=[_m("1982-08-28", "arsenal", 1, 1)])
    assert _lengths(output, "wins") == ["—", "—", "—"], "no run, not a run of nil"


def test_naming_a_kind_still_lists_its_runs_in_full(tmp_path):
    output = _run(tmp_path, "--of", "wins", "--top", "3")
    assert "1982-09-11" in output and "1982-09-25" in output


def test_a_listed_run_reports_how_long_it_lasted(tmp_path):
    output = _run(tmp_path, "--of", "unbeaten")
    assert "days" in output
    assert _listing(output)[0][-1] == "21", "11 September to 2 October"


def test_a_drought_is_measured_from_the_last_win_to_the_next(tmp_path):
    output = _run(tmp_path, "--of", "without-win", "--top", "1", matches=[
        _m("1982-01-01", "arsenal", 1, 0),
        _m("1982-01-08", "watford", 0, 1),
        _m("1982-01-15", "everton", 1, 1),
        _m("1982-01-31", "luton-town", 2, 0),
    ])
    assert _listing(output)[0][-1] == "30", "1 January to 31 January, win to win"


def test_an_unfinished_drought_is_marked_as_a_lower_bound(tmp_path):
    """A drought open at either end of the record is a lower bound, not a fact.

    Nothing here says when the drought that opens the record began, nor when
    the one it closes on was ended.
    """
    output = _run(tmp_path, "--of", "without-win")
    assert [row[-1] for row in _listing(output)] == ["7+", "7+"]


def test_a_named_kind_is_broken_down_by_side_without_being_asked(tmp_path):
    output = _run(tmp_path, "--of", "unbeaten")
    for side in ("combined", "home", "away"):
        assert f"unbeaten — {side}" in output


def test_each_side_is_listed_from_its_own_matches(tmp_path):
    """Four unbeaten all told, three of them at home, two away."""
    output = _run(tmp_path, "--of", "unbeaten")
    assert _listing(output, "combined")[0][0] == "4"
    assert _listing(output, "home")[0][0] == "3"
    assert _listing(output, "away")[0][0] == "2"


def test_no_split_gives_the_one_combined_table(tmp_path):
    output = _run(tmp_path, "--of", "unbeaten", "--no-split")
    assert "— combined" not in output and "— home" not in output
    assert _listing(output, side=None)[0][0] == "4"


def test_an_explicit_side_lists_that_side_alone(tmp_path):
    output = _run(tmp_path, "--of", "unbeaten", "--side", "home")
    assert "— combined" not in output and "— away" not in output
    assert _listing(output, "home")[0][0] == "3"


def test_a_side_with_no_such_run_says_so_rather_than_going_quiet(tmp_path):
    """Every side gets its say, including the one with nothing to report."""
    output = _run(tmp_path, "--of", "wins", matches=[
        _m("1982-08-28", "arsenal", 2, 0),
        _m("1982-09-04", "watford", 1, 0),
        _m("1982-09-11", "everton", 0, 1, home=False),
    ])
    assert "No run of wins — away" in output


def test_the_summary_figures_line_up_under_one_another(tmp_path):
    """A column of figures is meant to be read down, so units sit under units."""
    matches = [_m(f"1982-{month:02d}-01", "arsenal", 2, 0)
               for month in range(1, 11)]
    matches.append(_m("1982-11-01", "watford", 0, 1))
    output = _run(tmp_path, matches=matches)
    assert _lengths(output, "unbeaten")[0] == "10"
    assert _lengths(output, "losses")[0] == "1", "the fixture must mix widths"

    columns = {}
    for line in output.splitlines():
        cells = line.split("|")
        if len(cells) > 1 and cells[0].strip() in _RUN_LABELS:
            for index, cell in enumerate(cells[1:]):
                if "(" in cell:
                    columns.setdefault(index, set()).add(cell.index("("))
    assert columns, "no figures found to line up"
    for index, positions in columns.items():
        assert len(positions) == 1, f"column {index} does not line up: {positions}"
