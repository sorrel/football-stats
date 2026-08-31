import pytest

from football.ids import match_id, slugify


@pytest.mark.parametrize(
    "name,expected",
    [
        ("Brighton and Hove Albion", "brighton-and-hove-albion"),
        ("Manchester United", "manchester-united"),
        ("Nott'm Forest", "nottm-forest"),
        ("Bayern München", "bayern-munchen"),
        ("  Leeds   United  ", "leeds-united"),
        ("Wolverhampton Wanderers F.C.", "wolverhampton-wanderers-f-c"),
    ],
)
def test_slugify(name, expected):
    assert slugify(name) == expected


def test_slugify_rejects_a_name_with_no_usable_characters():
    with pytest.raises(ValueError):
        slugify("!!!")


def test_match_id_is_date_then_home_then_away():
    assert match_id("1983-05-21", "manchester-united", "brighton-and-hove-albion") == (
        "1983-05-21_manchester-united_brighton-and-hove-albion"
    )


def test_match_id_is_stable_regardless_of_which_club_was_scraped():
    from_brighton = match_id("1983-05-21", "manchester-united", "brighton-and-hove-albion")
    from_united = match_id("1983-05-21", "manchester-united", "brighton-and-hove-albion")
    assert from_brighton == from_united


def test_match_id_rejects_a_non_iso_date():
    with pytest.raises(ValueError):
        match_id("21/05/1983", "a", "b")
