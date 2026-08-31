"""Converting openfootball fixtures to canonical rows.

The naming risk is the point: this source says "Middlesbrough FC" where ours
says "Middlesbrough", and slugifying blindly would create a second club.
"""

from football.sources.openfootball import Fixture
from football.sources.openfootball_import import candidate_slugs, convert, resolve

KNOWN = {"brighton-hove-albion", "middlesbrough", "bournemouth", "crawley-town",
         "liverpool", "chelsea"}


def _fixture(**overrides):
    values = {"date": "2024-10-30", "kickoff": "19:45", "round": "Round of 16",
              "home": "Brighton & Hove Albion", "away": "Liverpool FC",
              "ht": ("0", "0"), "ft": ("2", "3"), "aet": ("", ""),
              "pens": ("", "")}
    values.update(overrides)
    return Fixture(**values)


def test_a_trailing_fc_is_not_part_of_the_name():
    assert "middlesbrough" in candidate_slugs("Middlesbrough FC")


def test_a_leading_afc_is_handled_too():
    assert "bournemouth" in candidate_slugs("AFC Bournemouth")


def test_resolution_prefers_a_club_we_already_hold():
    assert resolve("Liverpool FC", KNOWN) == "liverpool"
    assert resolve("Brighton & Hove Albion", KNOWN) == "brighton-hove-albion"


def test_an_unrecognised_name_resolves_to_nothing_rather_than_a_new_club():
    """Inventing a slug would silently create a duplicate of a club we hold."""
    assert resolve("Somewhere Rovers", KNOWN) == ""


def test_an_explicit_alias_wins():
    assert resolve("Spurs", KNOWN, {"Spurs": "tottenham-hotspur"}) == (
        "tottenham-hotspur")


def test_a_fixture_is_converted_with_its_half_time_score():
    rows, unresolved = convert([_fixture()], "2024-25", "English EFL Cup",
                               KNOWN, "brighton-hove-albion")
    assert unresolved == []
    row = rows[0]
    assert row["competition"] == "league-cup"
    assert (row["ht_home"], row["ht_away"]) == ("0", "0")
    assert (row["ft_home"], row["ft_away"]) == ("2", "3")
    assert row["kickoff"] == "19:45"
    assert row["source"] == "openfootball"
    assert row["match_id"] == "2024-10-30_brighton-hove-albion_liverpool"


def test_matches_not_involving_our_club_are_skipped():
    other = _fixture(home="Chelsea FC", away="Liverpool FC")
    rows, _ = convert([other], "2024-25", "English EFL Cup", KNOWN,
                      "brighton-hove-albion")
    assert rows == []


def test_an_unresolvable_opponent_is_reported_not_imported():
    odd = _fixture(away="Somewhere Rovers")
    rows, unresolved = convert([odd], "2024-25", "English EFL Cup", KNOWN,
                               "brighton-hove-albion")
    assert rows == [] and unresolved == ["Somewhere Rovers"]


def test_an_unknown_competition_is_refused():
    rows, problems = convert([_fixture()], "2024-25", "Spanish Cup", KNOWN,
                             "brighton-hove-albion")
    assert rows == [] and "unknown competition" in problems[0]


def test_a_shootout_is_carried_across_without_becoming_a_running_total():
    tie = _fixture(ft=("0", "0"), pens=("6", "7"), ht=("", ""))
    rows, _ = convert([tie], "2022-23", "English FA Cup", KNOWN,
                      "brighton-hove-albion")
    assert (rows[0]["ft_home"], rows[0]["ft_away"]) == ("0", "0")
    assert (rows[0]["pens_home"], rows[0]["pens_away"]) == ("6", "7")


def _row(**overrides):
    from football.parse.base import blank_row
    from football import schema
    row = blank_row(schema.MATCHES)
    row.update({"match_id": "m1", "date": "2019-01-05", "season": "2018-19",
                "home_club": "a", "away_club": "b", "competition": "fa-cup",
                "ft_home": "1", "ft_away": "3", "attendance": "10000",
                "venue": "dean-court", "source": "engsoccerdata"})
    row.update(overrides)
    return row


def test_merging_never_discards_what_the_other_source_supplied():
    """A plain upsert would replace the row and lose attendance and venue."""
    from football.sources.openfootball_import import merge_into
    existing = [_row()]
    incoming = [_row(attendance="", venue="", ht_home="0", ht_away="2",
                     source="openfootball")]
    written, added, enriched = merge_into(existing, incoming)
    assert (added, enriched) == (0, 1)
    assert written[0]["attendance"] == "10000"
    assert written[0]["venue"] == "dean-court"
    assert (written[0]["ht_home"], written[0]["ht_away"]) == ("0", "2")
    assert written[0]["source"] == "engsoccerdata+openfootball"


def test_merging_does_not_overwrite_a_value_already_known():
    from football.sources.openfootball_import import merge_into
    existing = [_row(ht_home="9")]
    incoming = [_row(ht_home="0", source="openfootball")]
    written, added, enriched = merge_into(existing, incoming)
    assert existing[0]["ht_home"] == "9"
    # Nothing was blank, so nothing changed and nothing needs rewriting.
    assert (added, enriched) == (0, 0) and written == []


def test_a_match_we_do_not_hold_is_added():
    from football.sources.openfootball_import import merge_into
    written, added, enriched = merge_into([], [_row(match_id="new")])
    assert (added, enriched) == (1, 0) and len(written) == 1


def test_a_country_code_is_separated_from_the_club_name():
    from football.sources.openfootball_import import split_country
    assert split_country("AEK Athen (GRE)") == ("AEK Athen", "Greece")
    assert split_country("Brighton & Hove Albion (ENG)") == (
        "Brighton & Hove Albion", "England")


def test_a_name_without_a_country_code_is_unchanged():
    from football.sources.openfootball_import import split_country
    assert split_country("Liverpool FC") == ("Liverpool FC", "")


def test_an_unmapped_country_code_keeps_the_code():
    """A wrong country name would be worse than an honest code."""
    from football.sources.openfootball_import import split_country
    assert split_country("Some Club (XYZ)") == ("Some Club", "XYZ")


def test_a_club_resolves_despite_its_country_code():
    assert resolve("Liverpool FC (ENG)", KNOWN) == "liverpool"


def test_both_names_for_the_conference_league_are_recognised():
    """The files use both across seasons."""
    from football.sources.openfootball_import import COMPETITIONS
    assert COMPETITIONS["UEFA Conference League"] == "conference-league"
    assert COMPETITIONS["UEFA Europa Conference League"] == "conference-league"


def test_the_fa_cup_round_of_16_is_recorded_as_round_five():
    """The other source calls it Round 5, and a century of ties are numbered."""
    from football.sources.openfootball_import import canonical_round
    assert canonical_round("fa-cup", "Round of 16") == "Round 5"


def test_european_rounds_keep_their_names():
    """They have no numbers, so there is nothing to normalise to."""
    from football.sources.openfootball_import import canonical_round
    assert canonical_round("europa-league", "Round of 16") == "Round of 16"
    assert canonical_round("champions-league", "Round of 16") == "Round of 16"


def test_the_round_of_16_is_a_different_number_in_each_cup():
    """The FA Cup's fifth round and the League Cup's fourth are both the
    round of 16, so one canonical name for both would be wrong."""
    from football.sources.openfootball_import import canonical_round
    assert canonical_round("fa-cup", "Round of 16") == "Round 5"
    assert canonical_round("league-cup", "Round of 16") == "Round 4"


def test_the_league_cup_quarter_final_is_round_five():
    """The other source numbers this competition to five and names no
    quarter-final, so leaving both spellings would rank one stage twice."""
    from football.sources.openfootball_import import canonical_round
    assert canonical_round("league-cup", "Quarter-final") == "Round 5"
    assert canonical_round("fa-cup", "Quarter-final") == "Quarter-final"
