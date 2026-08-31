from football.cache import PageCache
from football.crawl import crawl


class RecordingSource:
    """A stand-in page source; the real one arrives in Phase 2."""

    def __init__(self) -> None:
        self.requested: list[str] = []

    def fetch(self, key: str) -> str:
        self.requested.append(key)
        return f"<html>{key}</html>"


def test_crawl_stops_at_the_budget(tmp_path):
    source, cache = RecordingSource(), PageCache(tmp_path)
    result = crawl(["a", "b", "c", "d"], cache, source, budget=2, sleep=lambda _: None)
    assert result.fetched == 2
    assert result.remaining == 2
    assert source.requested == ["a", "b"]


def test_a_second_run_resumes_where_the_first_stopped(tmp_path):
    source, cache = RecordingSource(), PageCache(tmp_path)
    keys = ["a", "b", "c", "d"]
    crawl(keys, cache, source, budget=2, sleep=lambda _: None)
    crawl(keys, cache, source, budget=2, sleep=lambda _: None)
    assert source.requested == ["a", "b", "c", "d"]


def test_pages_already_cached_are_never_refetched(tmp_path):
    cache = PageCache(tmp_path)
    cache.put("a", "<html>already here</html>")
    source = RecordingSource()
    result = crawl(["a", "b"], cache, source, budget=10, sleep=lambda _: None)
    assert source.requested == ["b"]
    assert result.skipped == 1


def test_it_waits_between_requests_but_not_before_the_first(tmp_path):
    waits: list[float] = []
    crawl(["a", "b", "c"], PageCache(tmp_path), RecordingSource(),
          budget=10, delay=5.0, jitter=0.0, sleep=waits.append)
    assert waits == [5.0, 5.0]


def test_the_delay_is_jittered_so_requests_are_not_perfectly_regular(tmp_path):
    waits: list[float] = []
    crawl([str(n) for n in range(20)], PageCache(tmp_path), RecordingSource(),
          budget=20, delay=5.0, jitter=0.5, sleep=waits.append)
    assert len(set(waits)) > 1
    assert all(2.5 <= w <= 7.5 for w in waits)


def test_fetched_pages_land_in_the_cache(tmp_path):
    cache = PageCache(tmp_path)
    crawl(["a"], cache, RecordingSource(), budget=1, sleep=lambda _: None)
    assert cache.get("a") == "<html>a</html>"


class FailingSource:
    """A source whose fetch comes back empty, as a failing one might."""

    def fetch(self, key: str) -> str:
        return ""


def test_an_empty_result_is_not_cached(tmp_path):
    """Caching a failure turns a transient error into a permanent gap."""
    cache = PageCache(tmp_path)
    crawl(["a"], cache, FailingSource(), budget=1, sleep=lambda _: None)
    assert not cache.has("a")


def test_a_later_run_retries_what_failed(tmp_path):
    cache = PageCache(tmp_path)
    crawl(["a"], cache, FailingSource(), budget=1, sleep=lambda _: None)
    source = RecordingSource()
    crawl(["a"], cache, source, budget=1, sleep=lambda _: None)
    assert source.requested == ["a"]
    assert cache.get("a") == "<html>a</html>"


class PacedSource(RecordingSource):
    """A source that states its own polite interval, as HttpSource does."""

    def delay_for(self, key: str) -> float:
        return 9.0


def test_the_source_sets_the_pace_when_the_caller_does_not(tmp_path):
    """Politeness travels with the source, not with the caller's memory."""
    waits = []
    crawl(["a", "b"], PageCache(tmp_path), PacedSource(), budget=10,
          jitter=0.0, sleep=waits.append)
    assert waits == [9.0]


def test_an_explicit_delay_still_wins(tmp_path):
    waits = []
    crawl(["a", "b"], PageCache(tmp_path), PacedSource(), budget=10,
          delay=1.0, jitter=0.0, sleep=waits.append)
    assert waits == [1.0]


def test_a_source_with_no_opinion_gets_the_fallback(tmp_path):
    waits = []
    crawl(["a", "b"], PageCache(tmp_path), RecordingSource(), budget=10,
          jitter=0.0, sleep=waits.append)
    assert waits == [5.0]
