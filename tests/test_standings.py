from football.sources import standings

RECORD = {"season": "1982", "tier": "1", "division": "First Division",
          "subdivision": "None", "position": "22", "team_name":
          "Brighton & Hove Albion", "played": "42", "points": "40",
          "point_adjustment": "0"}

LEAGUE_SEASONS = {"1982-83": ("division-one", "1"),
                  "1996-97": ("division-three", "4")}


def test_a_start_year_becomes_a_season_label():
    assert standings.season_label("1982") == "1982-83"
    assert standings.season_label("1999") == "1999-00"


def test_the_id_identifies_one_club_season_in_one_competition():
    assert standings.season_id("1982-83", "brighton-hove-albion", "division-one") == (
        "1982-83_brighton-hove-albion_division-one")


def test_a_record_becomes_a_season_row():
    rows, skipped = standings.convert([RECORD], "Brighton & Hove Albion",
                                      "brighton-hove-albion", LEAGUE_SEASONS)
    assert skipped == []
    row = rows[0]
    assert row["position"] == "22" and row["points"] == "40"
    assert row["competition"] == "division-one" and row["tier"] == "1"
    assert row["source"] == "fjelstul"


def test_the_competition_comes_from_our_matches_not_the_source_name():
    """"First Division" was tier 1 until 1992 and tier 2 after — the name
    cannot say which competition it was, exactly as for matches."""
    rows, _ = standings.convert([RECORD], "Brighton & Hove Albion",
                                "brighton-hove-albion", LEAGUE_SEASONS)
    assert rows[0]["competition"] == "division-one"


def test_a_point_deduction_is_carried_across():
    record = {**RECORD, "season": "1996", "point_adjustment": "-2",
              "position": "23", "points": "47"}
    rows, _ = standings.convert([record], "Brighton & Hove Albion",
                                "brighton-hove-albion", LEAGUE_SEASONS)
    assert rows[0]["point_adjustment"] == "-2"


def test_records_for_other_clubs_are_ignored():
    other = {**RECORD, "team_name": "Arsenal"}
    rows, _ = standings.convert([other], "Brighton & Hove Albion",
                                "brighton-hove-albion", LEAGUE_SEASONS)
    assert rows == []


def test_a_season_we_hold_no_matches_for_is_reported_not_guessed():
    """Without our own matches we cannot say which competition it was."""
    record = {**RECORD, "season": "1899"}
    rows, skipped = standings.convert([record], "Brighton & Hove Albion",
                                      "brighton-hove-albion", LEAGUE_SEASONS)
    assert rows == [] and skipped == ["1899-00"]


def test_played_and_goals_are_not_carried_across():
    rows, _ = standings.convert([RECORD], "Brighton & Hove Albion",
                                "brighton-hove-albion", LEAGUE_SEASONS)
    assert "played" not in rows[0] and "goals_for" not in rows[0]


def test_a_former_name_is_matched_too():
    """Arsenal were Woolwich Arsenal until 1914, and this source says so."""
    record = {**RECORD, "team_name": "Woolwich Arsenal", "season": "1982"}
    rows, _ = standings.convert(
        [record], ["Arsenal", "Woolwich Arsenal"], "arsenal", LEAGUE_SEASONS)
    assert len(rows) == 1 and rows[0]["club"] == "arsenal"


def test_a_single_name_still_works():
    rows, _ = standings.convert([RECORD], "Brighton & Hove Albion",
                                "brighton-hove-albion", LEAGUE_SEASONS)
    assert len(rows) == 1


def test_another_club_is_still_ignored():
    other = {**RECORD, "team_name": "Chelsea"}
    rows, _ = standings.convert([other], ["Arsenal", "Woolwich Arsenal"],
                                "arsenal", LEAGUE_SEASONS)
    assert rows == []
