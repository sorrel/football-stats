"""Every source, declared once.

A source says what it covers, where its pages are, and how to turn them into
a `Batch`. Nothing else in the codebase needs to know a source exists — which
is the point: adding one (11v11, say) is a new entry here plus a builder, not
a change to the CLI, the store or the guards.

The pages themselves are fetched through the shared cache, so a re-parse
after a schema change costs nothing and never touches the network again.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from football.cache import PageCache
from football.sources.batch import Batch

#: Where each source's files live. Kept here rather than in the builders so
#: that what the crawler will request is readable in one place.
ENGSOCCER = "https://raw.githubusercontent.com/jalapic/engsoccerdata/master/data-raw"
FJELSTUL = ("https://raw.githubusercontent.com/jfjelstul/englishfootball/"
            "master/data-csv")
OPENFOOTBALL = "https://raw.githubusercontent.com/openfootball"
FOOTBALL_DATA = "https://www.football-data.co.uk/mmz4281"
WIKIPEDIA_API = ("https://en.wikipedia.org/w/api.php"
                 "?action=parse&prop=wikitext&format=json&page=")


@dataclass(frozen=True)
class Source:
    """One place data comes from."""

    name: str
    covers: str
    licence: str
    #: The pages to fetch. Receives the same context as `build`, because a
    #: page's address is not always derivable from a slug — a Wikipedia
    #: article is titled "Brighton & Hove Albion F.C.", not the slug.
    keys: Callable[[dict], list[str]]
    #: Turn the cached pages into rows. Receives only pages already fetched,
    #: so a partial crawl produces a partial batch rather than an error.
    build: Callable[[PageCache, str, dict], Batch]
    #: False while a source is known but not yet usable — 11v11 is behind a
    #: bot challenge, so it is listed and refused rather than silently absent.
    available: bool = True
    unavailable_because: str = ""


_REGISTRY: dict[str, Source] = {}


def register(source: Source) -> Source:
    _REGISTRY[source.name] = source
    return source


def all_sources() -> list[Source]:
    return [_REGISTRY[name] for name in sorted(_REGISTRY)]


def get(name: str) -> Source | None:
    return _REGISTRY.get(name)


def names() -> list[str]:
    return sorted(_REGISTRY)
