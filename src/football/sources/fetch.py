"""The one module permitted to reach the network.

Everything else in the package works from the page cache, which is what makes
a schema change a local re-parse rather than another download. The structure
test enforces that: no other module may import a network library.

**Politeness is built in, not remembered.** Each host carries its own pace
here, so no caller has to know that Wikipedia's API rate-limits far harder
than a static CSV host — it refused 19 of 31 requests spaced 1.5 seconds
apart, and accepted all but one at 5 seconds. A transient refusal is retried
with a growing wait rather than lost.
"""

from __future__ import annotations

import random
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable

#: Identifies the client honestly rather than impersonating a browser.
USER_AGENT = "football-results/0.1 (personal statistics database)"

DEFAULT_TIMEOUT = 30.0

#: Seconds between requests, by host. Finishing quickly is a non-goal; being
#: unobtrusive is the requirement, so every value here errs slow.
_HOST_DELAYS = {
    "en.wikipedia.org": 5.0,
    "www.wikipedia.org": 5.0,
    "raw.githubusercontent.com": 1.0,
    "api.github.com": 2.0,
    "www.football-data.co.uk": 1.0,
}

#: For a host we have not met. Cautious by default: a host that turns out to
#: tolerate more can be added above, but one we hammer cannot be un-hammered.
DEFAULT_DELAY = 3.0

#: Statuses worth trying again. A 404 will not become a 200 however long we
#: wait, so only rate limits and server-side faults are retried.
_RETRYABLE = frozenset({408, 425, 429, 500, 502, 503, 504})

DEFAULT_RETRIES = 4


class FetchError(Exception):
    """A page could not be retrieved."""


def delay_for(url: str) -> float:
    """The polite interval between requests to this URL's host."""
    host = urllib.parse.urlparse(url).netloc.lower()
    return _HOST_DELAYS.get(host, DEFAULT_DELAY)


class HttpSource:
    """A `PageSource` that fetches a URL over plain HTTP.

    The key *is* the URL. Per-request pacing belongs to `football.crawl`,
    which asks this source how long to wait; the retry backoff after a
    refusal belongs here, because only this module sees the refusal.
    """

    def __init__(
        self,
        timeout: float = DEFAULT_TIMEOUT,
        delay: float | None = None,
        retries: int = DEFAULT_RETRIES,
        opener=urllib.request.urlopen,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._timeout = timeout
        self._delay = delay
        self._retries = retries
        self._opener = opener
        self._sleep = sleep

    def delay_for(self, url: str) -> float:
        """How long to wait before the next request to this URL."""
        return self._delay if self._delay is not None else delay_for(url)

    def fetch(self, key: str) -> str:
        request = urllib.request.Request(key, headers={"User-Agent": USER_AGENT})
        last = ""

        for attempt in range(self._retries):
            try:
                with self._opener(request, timeout=self._timeout) as response:
                    return response.read().decode("utf-8", errors="replace")
            except urllib.error.HTTPError as exc:
                last = f"HTTP {exc.code}"
                if exc.code not in _RETRYABLE:
                    raise FetchError(f"{key}: {last}") from exc
                wait = _retry_after(exc) or _backoff(attempt, self.delay_for(key))
            except (urllib.error.URLError, TimeoutError, OSError) as exc:
                last = str(exc)
                wait = _backoff(attempt, self.delay_for(key))

            if attempt == self._retries - 1:
                break
            self._sleep(wait)

        raise FetchError(f"{key}: {last} after {self._retries} attempts")


def _retry_after(error: urllib.error.HTTPError) -> float | None:
    """The server's own instruction, which beats any guess of ours."""
    headers = getattr(error, "headers", None) or {}
    try:
        value = headers.get("Retry-After")
    except AttributeError:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _backoff(attempt: int, base: float) -> float:
    """Wait longer after each refusal, with jitter to avoid a lockstep retry."""
    return base * (2 ** attempt) * (1 + random.uniform(0, 0.25))
