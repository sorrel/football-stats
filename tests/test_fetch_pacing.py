"""Each host carries its own polite pace, and transient failures are retried.

No test touches the network: the opener and the clock are both injected.
"""

import urllib.error

import pytest

from football.sources.fetch import FetchError, HttpSource, delay_for


class _Response:
    def __init__(self, body=b"ok"):
        self._body = body

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def test_wikipedia_is_paced_more_slowly_than_the_others():
    """It rate-limited 19 of 31 requests at 1.5s intervals."""
    wiki = delay_for("https://en.wikipedia.org/w/api.php?action=parse")
    other = delay_for("https://www.football-data.co.uk/mmz4281/2324/E0.csv")
    assert wiki >= 5.0
    assert wiki > other


def test_an_unknown_host_gets_the_cautious_default():
    assert delay_for("https://example.test/thing") >= 2.0


def test_a_source_reports_the_delay_for_a_url():
    source = HttpSource()
    assert source.delay_for("https://en.wikipedia.org/x") >= 5.0


def test_an_explicit_delay_overrides_the_host_default():
    source = HttpSource(delay=0.25)
    assert source.delay_for("https://en.wikipedia.org/x") == 0.25


def test_a_rate_limited_request_is_retried_and_succeeds():
    attempts = []

    def opener(request, timeout=None):
        attempts.append(1)
        if len(attempts) < 3:
            raise urllib.error.HTTPError(
                request.full_url, 429, "Too Many Requests", {}, None)
        return _Response()

    waits = []
    source = HttpSource(opener=opener, sleep=waits.append)
    assert source.fetch("https://en.wikipedia.org/x") == "ok"
    assert len(attempts) == 3
    assert len(waits) == 2


def test_the_wait_grows_with_each_retry():
    """Backing off harder each time is what clears a rate limit."""
    def opener(request, timeout=None):
        raise urllib.error.HTTPError(request.full_url, 429, "slow down", {}, None)

    waits = []
    source = HttpSource(opener=opener, retries=3, sleep=waits.append)
    with pytest.raises(FetchError):
        source.fetch("https://en.wikipedia.org/x")
    assert waits == sorted(waits) and waits[-1] > waits[0]


def test_a_retry_after_header_is_obeyed():
    """The server saying how long to wait beats our own guess."""
    def opener(request, timeout=None):
        if not waits:
            raise urllib.error.HTTPError(
                request.full_url, 429, "slow", {"Retry-After": "7"}, None)
        return _Response()

    waits = []
    HttpSource(opener=opener, sleep=waits.append).fetch("https://x.test/y")
    assert waits == [7.0]


def test_a_missing_page_is_not_retried():
    """404 will not become a 200 however long we wait."""
    attempts = []

    def opener(request, timeout=None):
        attempts.append(1)
        raise urllib.error.HTTPError(request.full_url, 404, "Not Found", {}, None)

    with pytest.raises(FetchError):
        HttpSource(opener=opener, sleep=lambda _: None).fetch("https://x.test/y")
    assert len(attempts) == 1


def test_giving_up_reports_the_last_failure():
    def opener(request, timeout=None):
        raise urllib.error.HTTPError(request.full_url, 503, "Unavailable", {}, None)

    with pytest.raises(FetchError, match="503"):
        HttpSource(opener=opener, retries=2, sleep=lambda _: None).fetch(
            "https://x.test/y")
