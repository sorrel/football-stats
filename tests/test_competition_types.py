"""Each cup is its own type.

Grouping the FA Cup and the League Cup under one "domestic-cup" type meant
`--type domestic-cup` produced a combined figure nobody wants. A type now
names one competition, so a filter cannot silently merge two of them.
"""

from football.sources.engsoccer import competition_type


def test_each_domestic_cup_is_its_own_type():
    assert competition_type("fa-cup") == "fa-cup"
    assert competition_type("league-cup") == "league-cup"


def test_no_competition_is_typed_as_a_generic_domestic_cup():
    for slug in ("fa-cup", "league-cup", "premier-league", "europa-league"):
        assert competition_type(slug) != "domestic-cup"


def test_leagues_share_a_type_because_a_tier_comparison_is_meaningful():
    """Unlike cups, league seasons are genuinely comparable across divisions."""
    for slug in ("premier-league", "championship", "division-three-south"):
        assert competition_type(slug) == "league"


def test_play_offs_keep_their_own_type():
    assert competition_type("championship-play-offs") == "play-off"


def test_european_competitions_are_grouped():
    assert competition_type("europa-league") == "europe"
    assert competition_type("champions-league") == "europe"


def test_an_unrecognised_cup_becomes_its_own_type():
    """A new cup must not fall back into a bucket with another one."""
    assert competition_type("efl-trophy") == "efl-trophy"


def test_display_names_are_not_just_the_title_cased_slug():
    """"division-three-south" is the Third Division South, not the reverse."""
    from football.sources.engsoccer import competition_name
    assert competition_name("division-three-south") == "Third Division South"
    assert competition_name("division-three-north") == "Third Division North"


def test_play_offs_keep_their_hyphen():
    from football.sources.engsoccer import competition_name
    assert competition_name("championship-play-offs") == "Championship Play-offs"
    assert competition_name("division-two-play-offs") == "Division Two Play-offs"


def test_the_cups_have_proper_names():
    from football.sources.engsoccer import competition_name
    assert competition_name("fa-cup") == "FA Cup"
    assert competition_name("league-cup") == "League Cup"


def test_a_league_keeps_its_era_name():
    from football.sources.engsoccer import competition_name
    assert competition_name("premier-league") == "Premier League"
    assert competition_name("division-one") == "Division One"
