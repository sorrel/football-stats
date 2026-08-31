"""The source registry."""

from football.sources import builders  # noqa: F401  (registers the sources)
from football.sources import registry


def test_every_source_declares_what_it_covers_and_its_licence():
    for source in registry.all_sources():
        assert source.covers and source.licence


def test_the_sources_we_use_are_all_registered():
    names = set(registry.names())
    assert {"engsoccerdata", "football-data", "openfootball", "standings",
            "wikipedia-tables", "wikipedia-attendance"} <= names


def test_an_unknown_source_is_not_invented():
    assert registry.get("nonsense") is None


def test_a_source_we_cannot_use_is_listed_and_explained():
    """11v11 is known but blocked; hiding it would lose the reason why."""
    source = registry.get("11v11")
    assert source is not None
    assert not source.available
    assert "challenge" in source.unavailable_because


def test_every_available_source_can_name_its_pages():
    for source in registry.all_sources():
        if source.available:
            assert source.keys({"club_name": "Brighton & Hove Albion"})


def test_page_keys_are_urls():
    for source in registry.all_sources():
        for key in source.keys({"club_name": "Brighton & Hove Albion"}):
            assert key.startswith("https://")


def test_sources_are_listed_in_a_stable_order():
    assert registry.names() == sorted(registry.names())


def test_a_builder_creates_the_competitions_its_matches_name():
    """A match pointing at a competition we do not hold fails the rebuild."""
    from football.sources.builders import build_openfootball
    from football.cache import PageCache
    import tempfile

    with tempfile.TemporaryDirectory() as directory:
        batch = build_openfootball(PageCache(directory), "arsenal",
                                   {"clubs": [], "matches": []})
    named = {row["competition"] for row in batch.matches}
    declared = {row["slug"] for row in batch.competitions}
    assert named <= declared


def test_the_table_pages_follow_the_club_s_own_division():
    """Fetching the Premier League regardless of club looked right while
    only Brighton was loaded, and returned nothing for anyone below it."""
    from football.sources.builders import wikipedia_table_keys
    barrow = wikipedia_table_keys(
        {"league_seasons": {"2023-24": ("league-two", "4")}})
    assert all("League_Two" in key for key in barrow)
    assert not any("Premier_League" in key for key in barrow)


def test_a_club_that_changed_division_gets_both():
    from football.sources.builders import wikipedia_table_keys
    keys = wikipedia_table_keys({"league_seasons": {
        "2022-23": ("league-one", "3"), "2023-24": ("championship", "2")}})
    assert any("League_One" in key for key in keys)
    assert any("Championship" in key for key in keys)


def test_a_club_with_no_recent_seasons_falls_back_to_the_top_flight():
    from football.sources.builders import wikipedia_table_keys
    keys = wikipedia_table_keys({"league_seasons": {"1930-31": ("division-three", "3")}})
    assert all("Premier_League" in key for key in keys)


def test_the_table_builder_reads_the_pages_the_fetcher_downloaded():
    """The keys and the loop must not drift apart: a builder reading a
    different division from the one fetched finds nothing, silently."""
    import inspect

    from football.sources import builders
    source = inspect.getsource(builders.build_wikipedia_tables)
    assert "wikipedia_table_keys(context)" in source
    assert "_Premier_League" not in source, (
        "the builder hard-codes a division instead of using the keys")


def test_both_club_suffixes_are_offered():
    """Barrow are Barrow A.F.C.; the name gives no clue which it is."""
    from football.sources.builders import wikipedia_article_titles
    titles = wikipedia_article_titles("Barrow")
    assert "Barrow_F.C." in titles and "Barrow_A.F.C." in titles


def test_a_club_already_carrying_the_suffix_gets_one_title():
    from football.sources.builders import wikipedia_article_titles
    assert wikipedia_article_titles("AFC Bournemouth") == ["AFC_Bournemouth"]
    assert wikipedia_article_titles("Arsenal F.C.") == ["Arsenal_F.C."]


def test_an_api_error_is_not_a_page():
    """A 200 carrying 'no such page' must not be cached as content."""
    from football.cli_import import _is_api_error
    assert _is_api_error('{"error": {"code": "missingtitle"}}')
    assert not _is_api_error('{"parse": {"wikitext": {"*": "x"}}}')
    assert not _is_api_error("= English FA Cup 2019/20")
