"""Parsing the openfootball Football.TXT format.

The score grammar is the whole risk here: a single bracket means half time on
a plain line but full time on an extra-time line.
"""

from football.sources.openfootball import parse, parse_result

SAMPLE = """= English EFL Cup 2023/24

# Date       Tue Aug 8 2023 - Sun Feb 25 2024 (201d)

▪ Round 1
  Tue Aug 8 2023
    19:00  Huddersfield Town       v Middlesbrough FC         2-3 (1-1)
           Peterborough United     v Swindon Town             4-1 pen. (1-1, 1-0)

▪ Final
  Sun Feb 25 2024
    15:00  Chelsea FC              v Liverpool FC             0-1 a.e.t. (0-0)
"""


def test_a_plain_score_is_full_time_with_half_time_in_brackets():
    assert parse_result("2-3 (1-1)") == {"ft": ("2", "3"), "ht": ("1", "1")}


def test_a_shootout_records_pens_full_time_and_half_time():
    assert parse_result("4-1 pen. (1-1, 1-0)") == {
        "pens": ("4", "1"), "ft": ("1", "1"), "ht": ("1", "0")}


def test_a_shootout_with_one_bracket_gives_full_time_not_half_time():
    """The bracket is the stage before the shootout, which is full time."""
    assert parse_result("3-5 pen. (0-0)") == {"pens": ("3", "5"), "ft": ("0", "0")}


def test_extra_time_with_one_bracket_gives_full_time():
    assert parse_result("0-1 a.e.t. (0-0)") == {"aet": ("0", "1"), "ft": ("0", "0")}


def test_the_full_form_records_every_stage():
    assert parse_result("4-2 pen. 2-1 a.e.t. (2-1, 2-0)") == {
        "pens": ("4", "2"), "aet": ("2", "1"), "ft": ("2", "1"), "ht": ("2", "0")}


def test_an_unplayed_fixture_yields_nothing():
    assert parse_result("") == {}


def test_the_heading_gives_competition_and_season():
    document = parse(SAMPLE)
    assert document.competition == "English EFL Cup"
    assert document.season == "2023-24"


def test_every_played_fixture_is_read():
    assert len(parse(SAMPLE).fixtures) == 3


def test_club_names_and_kick_off_are_read():
    first = parse(SAMPLE).fixtures[0]
    assert first.home == "Huddersfield Town" and first.away == "Middlesbrough FC"
    assert first.kickoff == "19:00" and first.date == "2023-08-08"
    assert first.ft == ("2", "3") and first.ht == ("1", "1")


def test_rounds_are_normalised():
    rounds = {f.round for f in parse(SAMPLE).fixtures}
    assert rounds == {"Round 1", "Final"}


def test_a_fixture_with_no_kick_off_time_still_parses():
    second = parse(SAMPLE).fixtures[1]
    assert second.kickoff == "" and second.pens == ("4", "1")


def test_the_final_carries_its_extra_time_score():
    final = parse(SAMPLE).fixtures[-1]
    assert final.aet == ("0", "1") and final.ft == ("0", "0")
    assert final.round == "Final"


def test_the_year_rolls_forward_when_the_competition_crosses_new_year():
    """A cup runs August to May and the file omits the year once it is obvious."""
    text = """= English EFL Cup 2023/24

▪ Round 3
  Tue Dec 19 2023
    19:45  Everton FC               v Fulham FC               0-1 (0-0)

▪ Final
  Sun Feb 25
    15:00  Chelsea FC               v Liverpool FC            0-1 a.e.t. (0-0)
"""
    dates = [f.date for f in parse(text).fixtures]
    assert dates == ["2023-12-19", "2024-02-25"]


def test_a_club_whose_name_contains_v_is_not_split_wrongly():
    text = """= English EFL Cup 2023/24

▪ Round 1
  Tue Aug 8 2023
    19:00  Aston Villa             v Everton FC               2-1 (1-0)
"""
    fixture = parse(text).fixtures[0]
    assert fixture.home == "Aston Villa" and fixture.away == "Everton FC"


SPANNED = """= English FA Cup 2019/20

# Date       Fri Nov 8 2019 - Sat Aug 1 2020 (267d)

▪ Semi-finals
  Sat Jul 18
    18:00  Arsenal FC              v Manchester City          2-0 (1-0)

▪ Final
  Sat Aug 1
    17:30  Arsenal FC              v Chelsea FC               2-1 (1-1)
"""


def test_a_season_finishing_in_july_is_dated_from_the_declared_span():
    """The 2019-20 FA Cup finished in July and August 2020, not 2019."""
    dates = [f.date for f in parse(SPANNED).fixtures]
    assert dates == ["2020-07-18", "2020-08-01"]


def test_the_declared_span_is_read():
    from football.sources.openfootball import parse_span
    assert parse_span(SPANNED) == ("2019-11-08", "2020-08-01")


def test_a_file_with_no_span_still_parses():
    from football.sources.openfootball import parse_span
    assert parse_span("= English EFL Cup 2023/24\n") is None
    assert parse(SAMPLE.replace("# Date", "# Notes")).fixtures


def test_an_opening_august_stays_in_the_starting_year():
    """Without a span, August belongs to the season's start."""
    text = """= English EFL Cup 2023/24

▪ Round 1
  Tue Aug 8
    19:00  Everton FC               v Fulham FC               2-0 (1-0)
"""
    assert parse(text).fixtures[0].date == "2023-08-08"
