"""Head to head, split by where the match was played."""

from click.testing import CliRunner

from football import schema, store
from football.cli import cli
from football.parse.base import blank_row

US, THEM = "brighton-hove-albion", "crystal-palace"


def _match(date, gf, ga, home=True, neutral="", competition="division-one",
           **extra):
    row = blank_row(schema.MATCHES)
    row.update({
        "match_id": f"{date}_{US if home else THEM}_{THEM if home else US}",
        "date": date, "season": "1982-83",
        "home_club": US if home else THEM, "away_club": THEM if home else US,
        "competition": competition, "tier": "1", "neutral": neutral,
        "status": "played", "source": "test",
        "ft_home": str(gf if home else ga), "ft_away": str(ga if home else gf)})
    row.update({name: str(value) for name, value in extra.items()})
    return row


def _seed(data_dir, matches):
    store.write_table(data_dir, schema.CLUBS, [
        {"slug": s, "name": n, "former_names": "", "english_league": "true",
         "country": "England"}
        for s, n in ((US, "Brighton and Hove Albion"), (THEM, "Crystal Palace"))])
    store.write_table(data_dir, schema.COMPETITIONS, [
        {"slug": "division-one", "name": "Division One", "type": "league",
         "tier": "", "first_season": "", "last_season": ""},
        {"slug": "premier-league", "name": "Premier League", "type": "league",
         "tier": "", "first_season": "", "last_season": ""},
        {"slug": "fa-cup", "name": "FA Cup", "type": "fa-cup",
         "tier": "", "first_season": "", "last_season": ""}])
    store.write_table(data_dir, schema.VENUES, [])
    store.write_matches(data_dir, matches)


def _args(tmp_path):
    return ["--data-dir", str(tmp_path / "data"), "--db", str(tmp_path / "f.db")]


def _run(tmp_path, matches, extra=()):
    _seed(tmp_path / "data", matches)
    runner = CliRunner()
    runner.invoke(cli, [*_args(tmp_path), "rebuild"])
    # --club is a command option, so it follows the subcommand name.
    return runner.invoke(cli, [*_args(tmp_path), "h2h", THEM, "--club", US, *extra])


def test_home_and_away_are_shown_separately(tmp_path):
    result = _run(tmp_path, [
        _match("1983-01-01", 3, 1, home=True),
        _match("1983-02-01", 0, 2, home=False)])
    assert result.exit_code == 0
    assert "home" in result.output and "away" in result.output


def test_the_split_counts_each_side_correctly(tmp_path):
    result = _run(tmp_path, [
        _match("1983-01-01", 3, 1, home=True),
        _match("1983-01-08", 2, 0, home=True),
        _match("1983-02-01", 0, 2, home=False)])
    lines = [l for l in result.output.splitlines() if l.startswith(("home", "away"))]
    home = [l for l in lines if l.startswith("home")][0]
    away = [l for l in lines if l.startswith("away")][0]
    assert "2" in home.split("|")[1]
    assert "1" in away.split("|")[1]


def test_a_neutral_ground_is_its_own_row_not_folded_into_away(tmp_path):
    """A cup final at Wembley is not an away match, whoever is listed first."""
    result = _run(tmp_path, [
        _match("1983-01-01", 3, 1, home=True),
        _match("1983-05-21", 2, 2, home=False, neutral="true",
               competition="fa-cup")])
    assert "neutral" in result.output


def test_no_neutral_row_when_there_were_none(tmp_path):
    """A permanent row of zeros is noise."""
    result = _run(tmp_path, [_match("1983-01-01", 3, 1, home=True)])
    assert "neutral" not in result.output


def test_both_clubs_are_named_in_the_heading(tmp_path):
    result = _run(tmp_path, [_match("1983-01-01", 3, 1)])
    assert "Brighton and Hove Albion" in result.output
    assert "Crystal Palace" in result.output


def test_the_goal_columns_say_they_hold_goals(tmp_path):
    """A column headed with a club's name reads as though it held clubs."""
    result = _run(tmp_path, [_match("1983-01-01", 3, 1)])
    header = [l for l in result.output.splitlines() if "played" in l][0]
    assert "for" in header and "against" in header
    assert "Brighton" not in header and "Palace" not in header


def test_the_split_respects_a_competition_filter(tmp_path):
    result = _run(tmp_path, [
        _match("1983-01-01", 3, 1, home=True),
        _match("1983-05-21", 2, 2, home=False, neutral="true",
               competition="fa-cup")],
        extra=("--competition", "fa-cup"))
    assert "neutral" in result.output
    assert "home" not in result.output.split("venue")[-1].split("\n")[1]


def test_clubs_that_have_never_met_say_so(tmp_path):
    result = _run(tmp_path, [_match("1983-01-01", 3, 1)],
                  extra=("--competition", "fa-cup"))
    assert "never met" in result.output


def test_each_competition_gets_its_own_table(tmp_path):
    """A league meeting and a cup contest are different questions."""
    result = _run(tmp_path, [
        _match("1983-01-01", 3, 1, home=True),
        _match("1983-05-21", 2, 2, home=False, neutral="true",
               competition="fa-cup")])
    assert "League" in result.output and "FA Cup" in result.output
    headers = [l for l in result.output.splitlines() if l.startswith("venue")]
    assert len(headers) == 2


def test_the_totals_table_compares_the_competitions(tmp_path):
    result = _run(tmp_path, [
        _match("1983-01-01", 3, 1, home=True),
        _match("1983-05-21", 2, 2, home=False, competition="fa-cup")])
    totals = result.output.split("competition |")[-1]
    assert "League" in totals and "FA Cup" in totals and "total" in totals


def test_a_single_competition_needs_no_totals_table(tmp_path):
    """It would be that one competition twice over."""
    result = _run(tmp_path, [_match("1983-01-01", 3, 1, home=True)])
    assert "competition |" not in result.output


def test_cup_tables_count_the_contests_not_only_the_matches(tmp_path):
    """A 0-0 and its replay are two matches but one contest."""
    result = _run(tmp_path, [
        _match("1979-10-30", 0, 0, home=False, competition="fa-cup"),
        _match("1979-11-13", 4, 0, home=True, competition="fa-cup",
               is_replay="true",
               replay_of="1979-10-30_crystal-palace_brighton-hove-albion")])
    rows = {l.split("|")[0].strip(): [c.strip() for c in l.split("|")]
            for l in result.output.splitlines() if l.startswith(("home", "away"))}
    assert rows["away"][1] == "1" and rows["away"][2] == "1"  # one, one match
    assert rows["home"][1] == "0" and rows["home"][2] == "1"  # the replay only
    assert rows["home"][8] == "1", "the replay is counted where it was played"


def test_the_replay_column_says_which_count_it_is(tmp_path):
    """"replays" could as easily mean the draws that were replayed."""
    result = _run(tmp_path, [
        _match("1979-10-30", 0, 0, home=False, competition="fa-cup"),
        _match("1979-11-13", 4, 0, home=True, competition="fa-cup",
               is_replay="true")])
    assert "matches played as a replay" in result.output


def test_no_replay_note_when_there_were_none(tmp_path):
    result = _run(tmp_path, [_match("1983-01-01", 3, 1, competition="fa-cup")])
    assert "played as a replay" not in result.output


def test_the_league_table_has_no_cup_columns(tmp_path):
    """Contests, replays and penalties are not questions a league raises."""
    result = _run(tmp_path, [_match("1983-01-01", 3, 1)])
    header = [l for l in result.output.splitlines() if l.startswith("venue")][0]
    assert "contests" not in header and "replays" not in header


def test_the_league_is_broken_down_by_division(tmp_path):
    result = _run(tmp_path, [
        _match("1983-01-01", 3, 1, competition="division-one"),
        _match("2015-01-01", 1, 0, competition="premier-league")])
    table = result.output.split("League by division")[-1]
    assert "Division One" in table and "Premier League" in table


def test_divisions_come_in_the_order_they_were_played(tmp_path):
    result = _run(tmp_path, [
        _match("2015-01-01", 1, 0, competition="premier-league"),
        _match("1983-01-01", 3, 1, competition="division-one")])
    table = result.output.split("League by division")[-1]
    assert table.index("Division One") < table.index("Premier League")


def test_cups_are_broken_down_by_round(tmp_path):
    result = _run(tmp_path, [
        _match("1983-01-08", 1, 0, competition="fa-cup", round="Final"),
        _match("1983-01-01", 3, 1, competition="fa-cup", round="Round 3")])
    table = result.output.split("FA Cup by round")[-1]
    assert table.index("Round 3") < table.index("Final"), "the final comes last"


def test_a_round_never_reached_is_absent_not_a_row_of_zeros(tmp_path):
    result = _run(tmp_path, [
        _match("1983-01-01", 3, 1, competition="fa-cup", round="Round 3")])
    table = result.output.split("FA Cup by round")[-1]
    assert "Round 3" in table and "Round 4" not in table and "Final" not in table


def test_no_round_table_when_the_rounds_went_unrecorded(tmp_path):
    result = _run(tmp_path, [_match("1983-01-01", 3, 1, competition="fa-cup")])
    assert "FA Cup by round" not in result.output
