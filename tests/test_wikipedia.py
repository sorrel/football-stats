"""Parsing Wikipedia's structured season templates."""

from football.sources.wikipedia import (
    TableRow, clean_name, has_league_table, is_complete, parse_league_table)

TABLE = """
{{#invoke:Sports table|main|style=WDL|source=[https://example.test PL]
|team_order = ARS, BHA, BUR
|update=complete
|win_ARS=26|draw_ARS=7 |loss_ARS=5 |gf_ARS=71|ga_ARS=27
|win_BHA=14|draw_BHA=11|loss_BHA=13|gf_BHA=52|ga_BHA=46
|win_BUR=4 |draw_BUR=10|loss_BUR=24|gf_BUR=38|ga_BUR=75
|name_ARS=[[Arsenal F.C.|Arsenal]]
|name_BHA=[[Brighton & Hove Albion F.C.|Brighton & Hove Albion]]
|name_BUR=[[Burnley F.C.|Burnley]]
}}
"""


def test_a_page_without_the_template_yields_nothing():
    assert parse_league_table("just prose") == []
    assert not has_league_table("just prose")


def test_positions_come_from_the_team_order():
    rows = {row.code: row.position for row in parse_league_table(TABLE)}
    assert rows == {"ARS": 1, "BHA": 2, "BUR": 3}


def test_each_club_carries_its_record():
    brighton = [r for r in parse_league_table(TABLE) if r.code == "BHA"][0]
    assert (brighton.won, brighton.drawn, brighton.lost) == (14, 11, 13)
    assert (brighton.goals_for, brighton.goals_against) == (52, 46)
    assert brighton.played == 38


def test_club_names_lose_their_wiki_markup():
    brighton = [r for r in parse_league_table(TABLE) if r.code == "BHA"][0]
    assert brighton.name == "Brighton & Hove Albion"


def test_clean_name_handles_a_plain_link():
    assert clean_name("[[Arsenal F.C.]]") == "Arsenal F.C."


def test_points_are_three_for_a_win_in_a_modern_season():
    brighton = [r for r in parse_league_table(TABLE) if r.code == "BHA"][0]
    assert brighton.points(2025) == 53


def test_points_are_two_for_a_win_before_1981():
    """The rule changed in 1981-82, so the era must be explicit."""
    row = TableRow(code="X", name="X", position=1, won=10, drawn=5, lost=5,
                   goals_for=0, goals_against=0)
    assert row.points(1980) == 25
    assert row.points(1981) == 35


def test_a_deduction_is_applied_to_the_points():
    row = TableRow(code="X", name="X", position=1, won=10, drawn=5, lost=5,
                   goals_for=0, goals_against=0, point_adjustment=-2)
    assert row.points(2000) == 33


def test_a_completed_season_says_so():
    assert is_complete(TABLE)


def test_a_season_still_in_progress_is_not_complete():
    """A table being updated is a snapshot, not a final position."""
    assert not is_complete(TABLE.replace("|update=complete", "|update=21 March 2026"))


def test_a_club_with_no_record_is_skipped():
    """A team listed but with no figures has not finished a season."""
    partial = TABLE.replace("|win_BUR=4 |draw_BUR=10|loss_BUR=24", "")
    codes = {row.code for row in parse_league_table(partial)}
    assert codes == {"ARS", "BHA"}


def test_a_second_table_on_the_page_does_not_bleed_in():
    """Season articles often carry more than one table."""
    two = TABLE + "\n" + TABLE.replace("BHA", "ZZZ").replace("ARS", "YYY")
    codes = [row.code for row in parse_league_table(two)]
    assert "ZZZ" not in codes and "YYY" not in codes


def test_a_name_containing_a_pipe_is_read_whole():
    """The value is a wikilink, so it contains the delimiter itself."""
    assert clean_name("[[Brighton & Hove Albion F.C.|Brighton & Hove Albion]]") == (
        "Brighton & Hove Albion")
    rows = {r.code: r.name for r in parse_league_table(TABLE)}
    assert rows["BUR"] == "Burnley"


BOX = """
{{football box collapsible
| round      = [[Premier League]]
| date       = 24 May 2026
| time       = 16:00
| team1      = Brighton & Hove Albion
| score      = 2–1
| team2      = [[Manchester United F.C.|Manchester United]]
| stadium    = [[Falmer Stadium]]
| attendance = 31,729
| referee    = Someone
}}
"""


def test_a_match_box_is_read():
    from football.sources.wikipedia import parse_match_boxes
    box = parse_match_boxes(BOX)[0]
    assert box.date == "2026-05-24"
    assert box.home == "Brighton & Hove Albion"
    assert box.away == "Manchester United"
    assert box.attendance == "31729"
    assert box.kickoff == "16:00"


def test_a_date_becomes_iso():
    from football.sources.wikipedia import parse_date
    assert parse_date("12 July 2025") == "2025-07-12"
    assert parse_date("3 January 2026") == "2026-01-03"
    assert parse_date("nonsense") == ""


def test_an_attendance_loses_its_separator():
    from football.sources.wikipedia import parse_attendance
    assert parse_attendance("31,729") == "31729"


def test_a_crowd_of_zero_is_a_fact_not_a_gap():
    """Matches behind closed doors really did have no crowd."""
    from football.sources.wikipedia import parse_attendance
    assert parse_attendance("0 ([[Behind closed doors (sport)|Behind closed doors]])") == "0"


def test_a_blank_attendance_stays_unknown():
    from football.sources.wikipedia import parse_attendance
    assert parse_attendance("") == "" and parse_attendance("   ") == ""


def test_a_box_without_a_readable_date_is_skipped():
    from football.sources.wikipedia import parse_match_boxes
    assert parse_match_boxes(BOX.replace("24 May 2026", "TBC")) == []


def test_a_missing_kick_off_time_is_empty_not_invented():
    from football.sources.wikipedia import parse_match_boxes
    box = parse_match_boxes(BOX.replace("| time       = 16:00", "| time       ="))[0]
    assert box.kickoff == ""


def _match_row(date, home, away, attendance="", kickoff=""):
    from football import schema
    from football.parse.base import blank_row
    row = blank_row(schema.MATCHES)
    row.update({"match_id": f"{date}_{home}_{away}", "date": date,
                "season": "2025-26", "home_club": home, "away_club": away,
                "competition": "premier-league", "attendance": attendance,
                "kickoff": kickoff, "status": "played", "source": "test"})
    return row


def _boxes(**overrides):
    from football.sources.wikipedia import MatchBox
    values = {"date": "2026-05-24", "home": "Brighton & Hove Albion",
              "away": "Manchester United", "attendance": "31729",
              "kickoff": "16:00", "stadium": "Falmer Stadium"}
    values.update(overrides)
    return [MatchBox(**values)]


def _slug(name):
    from football.ids import slugify
    return slugify(name)


def test_an_attendance_is_filled_onto_a_match_we_hold():
    from football.sources.wikipedia import enrich_matches
    rows = [_match_row("2026-05-24", "brighton-hove-albion", "manchester-united")]
    filled, unmatched = enrich_matches(rows, _boxes(), "brighton-hove-albion", _slug)
    assert (filled, unmatched) == (1, [])
    assert rows[0]["attendance"] == "31729"
    assert rows[0]["kickoff"] == "16:00"
    assert rows[0]["source"] == "test+wikipedia"


def test_a_friendly_we_do_not_store_is_reported_not_inserted():
    """Club season articles cover friendlies; the database does not."""
    from football.sources.wikipedia import enrich_matches
    rows = []
    filled, unmatched = enrich_matches(rows, _boxes(date="2025-07-12"),
                                       "brighton-hove-albion", _slug)
    assert rows == [] and filled == 0 and unmatched == ["2025-07-12"]


def test_an_existing_attendance_is_never_overwritten():
    from football.sources.wikipedia import enrich_matches
    rows = [_match_row("2026-05-24", "brighton-hove-albion", "manchester-united",
                       attendance="99999")]
    enrich_matches(rows, _boxes(), "brighton-hove-albion", _slug)
    assert rows[0]["attendance"] == "99999"


def test_the_wrong_side_does_not_match():
    from football.sources.wikipedia import enrich_matches
    rows = [_match_row("2026-05-24", "manchester-united", "brighton-hove-albion")]
    filled, unmatched = enrich_matches(rows, _boxes(), "brighton-hove-albion", _slug)
    assert filled == 0 and unmatched == ["2026-05-24"]


def test_a_match_not_involving_our_club_is_ignored_entirely():
    from football.sources.wikipedia import enrich_matches
    rows = [_match_row("2026-05-24", "arsenal", "chelsea")]
    filled, unmatched = enrich_matches(
        rows, _boxes(home="Arsenal", away="Chelsea"), "brighton-hove-albion", _slug)
    assert filled == 0 and unmatched == []
