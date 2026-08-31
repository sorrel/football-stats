from football import schema
from football.parse.base import blank_row
from football.sources import footballdata as fd


def _record(**overrides):
    record = {"Div": "E0", "Date": "12/08/2023", "Time": "15:00",
              "HomeTeam": "Brighton", "AwayTeam": "Luton",
              "FTHG": "4", "FTAG": "1", "HTHG": "1", "HTAG": "0",
              "HY": "2", "AY": "2", "HR": "0", "AR": "0"}
    record.update(overrides)
    return record


def _match(**overrides):
    row = blank_row(schema.MATCHES)
    row.update({"match_id": "m1", "date": "2023-08-12", "season": "2023-24",
                "home_club": "brighton-hove-albion", "away_club": "luton-town",
                "competition": "premier-league", "ft_home": "4", "ft_away": "1",
                "source": "engsoccerdata"})
    row.update(overrides)
    return row


def test_dates_convert_from_british_to_iso():
    assert fd.parse_date("12/08/2023") == "2023-08-12"
    assert fd.parse_date("07/05/94") == "1994-05-07"
    assert fd.parse_date("07/05/04") == "2004-05-07"
    assert fd.parse_date("rubbish") == ""


def test_kick_off_times_are_normalised():
    assert fd.parse_time("15:00") == "15:00"
    assert fd.parse_time("9:30") == "09:30"
    assert fd.parse_time("") == ""


def test_season_urls_use_the_two_year_code():
    urls = fd.season_urls(1993, "https://example.test")
    assert urls[0] == "https://example.test/9394/E0.csv"
    assert len(urls) == 4


def test_a_record_without_our_club_is_ignored():
    assert fd.enrichment_for(_record(HomeTeam="Arsenal", AwayTeam="Chelsea"),
                             "Brighton") is None


def test_enrichment_carries_half_time_cards_and_kick_off():
    item = fd.enrichment_for(_record(), "Brighton")
    assert item["values"]["ht_home"] == "1"
    assert item["values"]["home_yellows"] == "2"
    assert item["values"]["kickoff"] == "15:00"
    assert item["we_are_home"] is True


def test_zero_cards_are_recorded_as_zero_not_as_unknown():
    item = fd.enrichment_for(_record(), "Brighton")
    assert item["values"]["home_reds"] == "0"


def test_a_blank_column_stays_unknown():
    item = fd.enrichment_for(_record(HY=""), "Brighton")
    assert "home_yellows" not in item["values"]


def test_enrichment_fills_blank_fields_on_the_matching_row():
    match = _match()
    items = [fd.enrichment_for(_record(), "Brighton")]
    enriched, unplaced = fd.apply_to([match], items, "brighton-hove-albion")
    assert enriched == 1 and unplaced == []
    assert (match["ht_home"], match["ht_away"]) == ("1", "0")
    assert match["source"] == "engsoccerdata+football-data"


def test_it_never_overwrites_a_value_that_is_already_known():
    """A hand correction outranks this source."""
    match = _match(ht_home="9", source="engsoccerdata+manual")
    items = [fd.enrichment_for(_record(), "Brighton")]
    fd.apply_to([match], items, "brighton-hove-albion")
    assert match["ht_home"] == "9"


def test_a_record_that_matches_nothing_is_reported_not_inserted():
    matches = [_match()]
    items = [fd.enrichment_for(_record(Date="01/01/2020"), "Brighton")]
    enriched, unplaced = fd.apply_to(matches, items, "brighton-hove-albion")
    assert len(matches) == 1
    assert enriched == 0 and unplaced == ["2020-01-01"]


def test_the_wrong_side_does_not_match():
    """Our club playing away cannot be matched to a home fixture."""
    matches = [_match()]
    items = [fd.enrichment_for(
        _record(HomeTeam="Luton", AwayTeam="Brighton"), "Brighton")]
    enriched, unplaced = fd.apply_to(matches, items, "brighton-hove-albion")
    assert enriched == 0 and unplaced == ["2023-08-12"]


def test_aliases_are_learned_from_fixtures_both_sources_share():
    """A club name is pinned by evidence, never guessed from spelling."""
    match = _match()  # 2023-08-12, Brighton home to luton-town
    items = [fd.enrichment_for(_record(), "Brighton")]
    aliases = fd.learn_aliases([match], items, "brighton-hove-albion")
    assert aliases == {"Luton": "luton-town"}


def test_a_name_with_no_shared_fixture_is_not_invented():
    items = [fd.enrichment_for(_record(Date="01/01/2020"), "Brighton")]
    assert fd.learn_aliases([_match()], items, "brighton-hove-albion") == {}


def test_a_full_match_can_be_built_for_a_season_the_primary_source_lacks():
    item = fd.enrichment_for(_record(), "Brighton")
    row = fd.to_match(item, {"Brighton": "brighton-hove-albion",
                             "Luton": "luton-town"}, "2023-24")
    assert row["match_id"] == "2023-08-12_brighton-hove-albion_luton-town"
    assert (row["ft_home"], row["ft_away"]) == ("4", "1")
    assert (row["ht_home"], row["ht_away"]) == ("1", "0")
    assert row["competition"] == "premier-league"
    assert row["source"] == "football-data"


def test_building_a_match_refuses_to_guess_an_unpinned_club():
    import pytest
    item = fd.enrichment_for(_record(), "Brighton")
    with pytest.raises(KeyError, match="Luton"):
        fd.to_match(item, {"Brighton": "brighton-hove-albion"}, "2023-24")


def test_a_fixture_with_no_score_is_not_a_match():
    import pytest
    item = fd.enrichment_for(_record(FTHG="", FTAG=""), "Brighton")
    with pytest.raises(ValueError, match="no score"):
        fd.to_match(item, {"Brighton": "brighton-hove-albion",
                           "Luton": "luton-town"}, "2023-24")


def test_a_byte_order_mark_does_not_corrupt_the_first_column():
    """Some seasons carry a BOM; left in place it hides the Div column."""
    with_bom = "﻿Div,Date,HomeTeam,AwayTeam\nE0,12/08/2023,Brighton,Luton\n"
    parsed = fd.records(with_bom)
    assert parsed[0]["Div"] == "E0"


def test_records_handles_a_file_without_a_mark():
    plain = "Div,Date,HomeTeam,AwayTeam\nE0,12/08/2023,Brighton,Luton\n"
    assert fd.records(plain)[0]["Div"] == "E0"


def test_an_empty_file_yields_no_records():
    assert fd.records("") == []


def test_a_built_match_records_its_tier():
    item = fd.enrichment_for(_record(), "Brighton")
    row = fd.to_match(item, {"Brighton": "brighton-hove-albion",
                             "Luton": "luton-town"}, "2023-24")
    assert row["tier"] == "1"


def _slugify(name):
    from football.ids import slugify
    return slugify(name)


def _held(date, home, away, gf="2", ga="1"):
    return {"date": date, "home_club": home, "away_club": away,
            "ft_home": gf, "ft_away": ga}


def _fixture_record(date, home, away, gf="2", ga="1"):
    return {"Date": date, "HomeTeam": home, "AwayTeam": away,
            "FTHG": gf, "FTAG": ga}


def test_our_name_is_found_by_fixtures_lining_up_not_by_spelling():
    """This source writes 'West Brom', which shares a word with 'West Ham'."""
    held = [_held(f"2020-01-0{n}", "west-bromwich-albion", "arsenal")
            for n in range(1, 8)]
    records = [_fixture_record(f"0{n}/01/2020", "West Brom", "Arsenal")
               for n in range(1, 8)]
    # West Ham play on the same Saturdays, with different scores.
    records += [_fixture_record(f"0{n}/01/2020", "West Ham", "Chelsea", "0", "3")
                for n in range(1, 8)]
    assert fd.find_our_name(records, held, "west-bromwich-albion", minimum=5) == "West Brom"


def test_a_wrong_club_sharing_a_word_is_not_chosen():
    held = [_held(f"2020-02-0{n}", "nottingham-forest", "arsenal")
            for n in range(1, 8)]
    records = [_fixture_record(f"0{n}/02/2020", "Nott'm Forest", "Arsenal")
               for n in range(1, 8)]
    records += [_fixture_record(f"0{n}/02/2020", "Forest Green", "Chelsea",
                                "0", "3") for n in range(1, 8)]
    assert fd.find_our_name(records, held, "nottingham-forest", minimum=5) == "Nott'm Forest"


def test_a_name_sharing_no_words_at_all_is_still_found():
    """'QPR' and 'Queens Park Rangers' have nothing in common as text."""
    held = [_held(f"2020-03-0{n}", "queens-park-rangers", "arsenal")
            for n in range(1, 8)]
    records = [_fixture_record(f"0{n}/03/2020", "QPR", "Arsenal") for n in range(1, 8)]
    assert fd.find_our_name(records, held, "queens-park-rangers", minimum=5) == "QPR"


def test_a_coincidental_score_is_rejected_by_the_margin():
    """Measured on the real cache, unrelated clubs reach 50 alignments by
    chance while the right name reaches 1,446. A close call is no answer."""
    held = [_held(f"2020-01-{n:02d}", "rochdale", "arsenal") for n in range(1, 26)]
    records = [_fixture_record(f"{n:02d}/01/2020", "Rochdale", "Arsenal")
               for n in range(1, 26)]
    # A club aligning almost as often is coincidence, not identity.
    records += [_fixture_record(f"{n:02d}/01/2020", "Barrow", "Arsenal")
                for n in range(1, 25)]
    assert fd.find_our_name(records, held, "rochdale") == ""


def test_a_clear_winner_is_accepted():
    held = [_held(f"2020-01-{n:02d}", "rochdale", "arsenal") for n in range(1, 26)]
    records = [_fixture_record(f"{n:02d}/01/2020", "Rochdale", "Arsenal")
               for n in range(1, 26)]
    records += [_fixture_record("01/01/2020", "Barrow", "Arsenal")]
    assert fd.find_our_name(records, held, "rochdale") == "Rochdale"


def test_too_few_alignments_returns_nothing():
    """A couple of coincidental fixtures must not decide it."""
    held = [_held("2020-01-01", "rochdale", "arsenal")]
    records = [_fixture_record("01/01/2020", "Barrow", "Arsenal")]
    assert fd.find_our_name(records, held, "rochdale", minimum=5) == ""


def test_a_club_at_home_on_the_same_day_does_not_score():
    """Same date and side, different scoreline: not our match."""
    held = [_held(f"2020-01-0{n}", "rochdale", "arsenal", "2", "1")
            for n in range(1, 9)]
    records = [_fixture_record(f"0{n}/01/2020", "Rochdale", "Arsenal", "2", "1")
               for n in range(1, 9)]
    records += [_fixture_record(f"0{n}/01/2020", "Barrow", "Chelsea", "4", "0")
                for n in range(1, 9)]
    assert fd.find_our_name(records, held, "rochdale", minimum=5) == "Rochdale"


def test_with_no_matches_held_nothing_can_be_identified():
    """There is no evidence to weigh, so no guess is made."""
    assert fd.find_our_name([_fixture_record("01/01/2020", "Brighton", "Luton")], [],
                            "brighton-hove-albion") == ""


