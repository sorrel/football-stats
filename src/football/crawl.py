"""Paced, resumable crawling.

Finishing quickly is a non-goal. Two controls keep the crawl unobtrusive: a
jittered delay between requests, and a per-run page budget so each invocation
stops cleanly and the next one resumes from the manifest.
"""

import random
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Protocol

from football.cache import PageCache


class PageSource(Protocol):
    """Anything that can turn a page key into page text.

    A source may also offer `delay_for(key)`, saying how long to wait before
    its next request. Politeness then travels with the source rather than
    depending on every caller knowing that one host rate-limits far harder
    than another.
    """

    def fetch(self, key: str) -> str: ...


@dataclass(frozen=True)
class CrawlResult:
    fetched: int
    skipped: int
    remaining: int


#: Used only when neither the caller nor the source says otherwise.
FALLBACK_DELAY = 5.0


def _delay_for(source: PageSource, key: str, delay: float | None) -> float:
    """How long to wait before fetching `key`.

    An explicit delay wins; otherwise the source is asked. A caller who has
    not thought about pacing gets the source's own polite default rather than
    a number that happened to suit a different host.
    """
    if delay is not None:
        return delay
    ask = getattr(source, "delay_for", None)
    return ask(key) if callable(ask) else FALLBACK_DELAY


def crawl(
    keys: Iterable[str],
    cache: PageCache,
    source: PageSource,
    budget: int,
    delay: float | None = None,
    jitter: float = 0.3,
    sleep: Callable[[float], None] = time.sleep,
) -> CrawlResult:
    """Fetch up to `budget` uncached pages, pausing between each."""
    fetched = skipped = 0
    outstanding = []

    for key in keys:
        if cache.has(key):
            skipped += 1
            continue
        if fetched >= budget:
            outstanding.append(key)
            continue
        if fetched:
            wait = _delay_for(source, key, delay)
            sleep(wait * (1 + random.uniform(-jitter, jitter)))
        text = source.fetch(key)
        fetched += 1
        # An empty page is never a valid result, and caching one poisons the
        # entry: the next run sees it as already fetched and skips it, so a
        # transient failure becomes a permanent gap.
        if text.strip():
            cache.put(key, text)

    return CrawlResult(fetched=fetched, skipped=skipped, remaining=len(outstanding))
