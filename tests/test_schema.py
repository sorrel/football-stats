from football import schema


def test_every_table_key_is_one_of_its_own_fields():
    for table in schema.TABLES:
        assert table.key in table.field_names(), (
            f"{table.name} key {table.key!r} is not a declared field"
        )


def test_field_names_are_unique_within_a_table():
    for table in schema.TABLES:
        names = table.field_names()
        assert len(names) == len(set(names)), f"duplicate field in {table.name}"


def test_every_field_kind_is_known():
    known = {"text", "int", "bool", "date", "time"}
    for table in schema.TABLES:
        for field in table.fields:
            assert field.kind in known, f"{table.name}.{field.name}: {field.kind}"


def test_matches_declares_the_spec_columns():
    expected = (
        "match_id", "date", "kickoff", "season",
        "home_club", "away_club", "neutral", "venue",
        "competition", "tier", "round", "leg",
        "ht_home", "ht_away", "ft_home", "ft_away",
        "aet_home", "aet_away", "pens_home", "pens_away",
        "is_replay", "replay_of", "attendance",
        "home_yellows", "away_yellows", "home_reds", "away_reds",
        "status", "abandoned_reason", "source",
    )
    assert schema.MATCHES.field_names() == expected


def test_every_match_records_which_dataset_it_came_from():
    field = {f.name: f for f in schema.MATCHES.fields}["source"]
    assert field.required, "a match with no known provenance cannot be adjudicated"


def test_competitions_record_when_they_ran():
    names = schema.COMPETITIONS.field_names()
    assert "first_season" in names and "last_season" in names


def test_no_source_url_column_anywhere():
    for table in schema.TABLES:
        for field in table.fields:
            assert "url" not in field.name, "source URLs are deliberately not stored"
