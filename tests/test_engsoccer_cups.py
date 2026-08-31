"""Play-off and League Cup conversion.

The two-legged tie is the case that matters: it has the same two clubs, the
same round and two dates, so anything that infers replays from dates alone
will call the second leg a replay.
"""

from football.sources import engsoccer as e


def _playoff(**overrides):
    record = {"Date": "1991-05-19", "Season": "1990",
              "home": "Brighton & Hove Albion", "visitor": "Millwall",
              "FT": "4-1", "hgoal": "4", "vgoal": "1", "division": "2",
              "round": "s", "tie": "leg1", "htier": "2", "vtier": "2",
              "aet": "NA", "pen": "NA", "pens": "NA", "hp": "NA", "vp": "NA",
              "Venue": "NA", "attendance": "16,000", "neutral": "NA"}
    record.update(overrides)
    return record


def _leaguecup(**overrides):
    record = {"Date": "1960-10-20", "Season": "1960", "home": "Notts County",
              "visitor": "Brighton & Hove Albion", "FT": "1-3", "hgoal": "1",
              "vgoal": "3", "round": "2", "tie": "initial", "leg": "0",
              "aet": "NA", "pens": "NA", "Venue": "NA", "attendance": "NA"}
    record.update(overrides)
    return record


def test_a_play_off_is_not_filed_as_a_league_match():
    row = e.playoff_match(_playoff())
    assert row["competition"] == "division-two-play-offs"


def test_play_off_competitions_are_named_for_their_era():
    assert e.playoff_competition("2", 2015)[0] == "championship-play-offs"
    assert e.playoff_competition("2", 1990)[0] == "division-two-play-offs"


def test_the_two_legs_of_a_semi_final_are_recorded_as_legs():
    first = e.playoff_match(_playoff(tie="leg1"))
    second = e.playoff_match(_playoff(tie="leg2", Date="1991-05-22",
                                      home="Millwall",
                                      visitor="Brighton & Hove Albion"))
    assert (first["leg"], second["leg"]) == ("1", "2")
    assert first["is_replay"] == "" and second["is_replay"] == ""


def test_a_second_leg_is_never_treated_as_a_replay():
    first = e.playoff_match(_playoff(tie="leg1"))
    second = e.playoff_match(_playoff(tie="leg2", Date="1991-05-22",
                                      home="Millwall",
                                      visitor="Brighton & Hove Albion"))
    e.link_replays([first, second])
    assert second["replay_of"] == "" and second["is_replay"] == ""


def test_a_replay_points_at_the_tie_it_replays():
    initial = e.leaguecup_match(_leaguecup(tie="initial", FT="1-1"))
    replay = e.leaguecup_match(_leaguecup(tie="replay1", Date="1960-10-27",
                                          home="Brighton & Hove Albion",
                                          visitor="Notts County", FT="2-0"))
    e.link_replays([initial, replay])
    assert replay["is_replay"] == "true"
    assert replay["replay_of"] == initial["match_id"]
    assert initial["is_replay"] == ""


def test_a_league_cup_tie_records_its_round_and_attendance():
    row = e.leaguecup_match(_leaguecup(attendance="12,345"))
    assert row["competition"] == "league-cup"
    assert row["round"] == "Round 2"
    assert row["attendance"] == "12345"


def test_a_single_match_tie_has_no_leg():
    assert e.leaguecup_match(_leaguecup(leg="0"))["leg"] == ""


def test_extra_time_still_leaves_the_ninety_minute_score_unknown():
    row = e.playoff_match(_playoff(aet="yes", FT="2-1"))
    assert (row["aet_home"], row["aet_away"]) == ("2", "1")
    assert row["ft_home"] == ""


def test_a_shootout_in_a_play_off_is_its_own_tally():
    row = e.playoff_match(_playoff(aet="yes", FT="1-1", pen="yes", hp="4", vp="3"))
    assert (row["pens_home"], row["pens_away"]) == ("4", "3")


def test_scores_fall_back_to_the_goal_columns():
    row = e.leaguecup_match(_leaguecup(FT="NA", hgoal="3", vgoal="2"))
    assert (row["ft_home"], row["ft_away"]) == ("3", "2")


def test_round_labels_are_normalised_to_one_spelling():
    """The source mixes "Final"/"final" and "Semi-final"/"semi" in one file."""
    assert e.round_name("final") == e.round_name("Final") == "Final"
    assert e.round_name("semi") == e.round_name("Semi-final") == "Semi-final"
    assert e.round_name("prelim") == "Preliminary Round"
    assert e.round_name("4") == "Round 4"


def test_a_two_legged_final_is_two_legs_not_a_replay():
    """League Cup finals were played over two legs until 1966."""
    first = e.leaguecup_match(_leaguecup(
        round="final", tie="initial", leg="1", Date="1961-08-22",
        home="Rotherham United", visitor="Aston Villa", FT="2-0"))
    second = e.leaguecup_match(_leaguecup(
        round="Final", tie="initial", leg="2", Date="1961-09-05",
        home="Aston Villa", visitor="Rotherham United", FT="3-0"))
    e.link_replays([first, second])
    assert (first["leg"], second["leg"]) == ("1", "2")
    assert first["round"] == second["round"] == "Final"
    assert second["is_replay"] == "" and second["replay_of"] == ""


def _fa(**overrides):
    record = {"Date": "1946-01-05", "Season": "1945", "home": "Brighton & Hove Albion",
              "visitor": "Arsenal", "FT": "1-1", "round": "3", "tie": "leg1",
              "aet": "NA", "pen": "NA", "pens": "NA", "hp": "NA", "vp": "NA",
              "Venue": "NA", "attendance": "NA", "nonmatch": "NA", "notes": "NA",
              "neutral": "NA"}
    record.update(overrides)
    return record


def test_the_two_legged_fa_cup_of_1945_is_legs_not_replays():
    """1945-46 is the only two-legged FA Cup, and the exception matters.

    Brighton beat Romford 3-1 and then played them again a week later. A
    replay follows a draw, so a second meeting after a decisive result cannot
    be one. In the source's 111 leg-one ties only 18% were drawn, against
    3,151 of 3,154 replays whose original tie was drawn.

    Dates alone cannot separate the two — a second leg swaps grounds exactly
    as a replay does — which is why the source's `tie` column is read instead.
    """
    first = e.facup_match(_fa(tie="leg1"))
    second = e.facup_match(_fa(tie="leg2", Date="1946-01-09",
                               home="Arsenal", visitor="Brighton & Hove Albion"))
    e.link_replays([first, second])
    assert (first["leg"], second["leg"]) == ("1", "2")
    assert second["is_replay"] == "" and second["replay_of"] == ""


def test_an_fa_cup_replay_is_still_a_replay():
    first = e.facup_match(_fa(tie="initial"))
    second = e.facup_match(_fa(tie="replay", Date="1946-01-09"))
    e.link_replays([first, second])
    assert second["is_replay"] == "true"
    assert second["replay_of"] == first["match_id"]


def test_the_same_clubs_twice_in_a_week_in_different_competitions():
    """Forest hosted Leeds twice in a week: once in the league, once in the cup.

    Neither is a replay of the other, and grouping by competition is what
    keeps them apart.
    """
    league = e.league_match({
        "Date": "2026-08-24", "Season": "2026", "home": "Nottingham Forest",
        "visitor": "Leeds United", "FT": "1-0", "hgoal": "1", "vgoal": "0",
        "division": "1", "tier": "1"})
    cup = e.leaguecup_match(_leaguecup(
        Date="2026-08-27", Season="2026", home="Nottingham Forest",
        visitor="Leeds United", FT="2-1", round="2", tie="initial", leg="0"))
    e.link_replays([league, cup])
    assert league["competition"] != cup["competition"]
    assert cup["is_replay"] == "" and cup["replay_of"] == ""
    assert league["is_replay"] == ""
