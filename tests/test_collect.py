"""`collect` runs fetch then import for a club across every available source.

The point is that it does this by reading the registry rather than a fixed
list, so a source added or withdrawn later changes what `collect` does
without anyone touching this command.

Each source's write is committed, and the database rebuilt, before the next
source runs — without that, only the first source in a run could ever be
written: the next one's write would find the first one's, still
uncommitted, and refuse. These tests run against a real (throwaway) git
repository rather than a faked one, because that refusal is exactly the
behaviour under test.
"""

import subprocess

from click.testing import CliRunner

from football import schema, store
from football.cache import PageCache
from football.cli import cli
from football.parse.base import blank_row
from football.sources import registry
from football.sources.batch import Batch


def _git(cwd, *args):
    result = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    return result


def _seed_and_commit(tmp_path):
    data_dir = tmp_path / "data"
    store.write_table(data_dir, schema.CLUBS, [])
    store.write_table(data_dir, schema.COMPETITIONS, [])
    store.write_table(data_dir, schema.VENUES, [])
    store.write_matches(data_dir, [])

    _git(tmp_path, "init", "--quiet")
    _git(tmp_path, "config", "user.email", "test@example.com")
    _git(tmp_path, "config", "user.name", "Test")
    _git(tmp_path, "add", "data")
    _git(tmp_path, "commit", "--quiet", "-m", "seed")


def _source(name, *, available=True, unavailable_because="", keys=None,
            build=None):
    return registry.Source(
        name=name, covers="test", licence="test",
        keys=keys or (lambda context: []),
        build=build or (lambda cache, club, context: Batch()),
        available=available, unavailable_because=unavailable_because)


def _run(tmp_path, args):
    _seed_and_commit(tmp_path)
    return CliRunner().invoke(cli, [
        "--data-dir", str(tmp_path / "data"), "--db", str(tmp_path / "f.db"),
        "--cache-dir", str(tmp_path / "cache"), *args])


def test_unavailable_sources_are_skipped(tmp_path, monkeypatch):
    """A source behind a bot challenge (11v11, say) must not be attempted."""
    monkeypatch.setattr(registry, "_REGISTRY", {})
    registry.register(_source("alpha"))
    registry.register(_source("blocked", available=False,
                              unavailable_because="behind a bot challenge"))

    result = _run(tmp_path, ["collect", "--club", "rochdale"])

    assert result.exit_code == 0
    assert "Collecting rochdale from 1 source(s): alpha." in result.output
    assert "blocked" not in result.output


def test_a_source_with_no_pages_cached_fails_without_stopping_the_rest(
        tmp_path, monkeypatch):
    """One source failing must not stop the others being collected."""
    monkeypatch.setattr(registry, "_REGISTRY", {})
    # "alpha" has nothing cached (its build is never called, so it can
    # raise if it somehow were).
    registry.register(_source(
        "alpha",
        build=lambda cache, club, context: (_ for _ in ()).throw(
            AssertionError("must not be reached: nothing was cached"))))
    # "beta" has a page already cached, so its import proceeds normally.
    cache = PageCache(tmp_path / "cache")
    cache.put("page-1", "<html></html>")
    registry.register(_source("beta", keys=lambda context: ["page-1"]))

    result = _run(tmp_path, ["collect", "--club", "rochdale"])

    assert result.exit_code == 0
    assert "== alpha ==" in result.output
    assert "No pages cached for alpha" in result.output
    assert "== beta ==" in result.output
    assert "1 of 2 source(s) could not be collected: alpha." in result.output
    assert "Nothing new to collect." in result.output


def test_every_available_source_that_has_pages_is_imported(
        tmp_path, monkeypatch):
    monkeypatch.setattr(registry, "_REGISTRY", {})
    cache = PageCache(tmp_path / "cache")
    cache.put("page-1", "<html></html>")
    registry.register(_source("alpha", keys=lambda context: ["page-1"]))

    result = _run(tmp_path, ["collect", "--club", "rochdale"])

    assert result.exit_code == 0
    assert "alpha: nothing to change" in result.output
    assert "could not be collected" not in result.output
    assert "Nothing new to collect." in result.output


def test_dry_run_writes_and_commits_nothing(tmp_path, monkeypatch):
    monkeypatch.setattr(registry, "_REGISTRY", {})
    cache = PageCache(tmp_path / "cache")
    cache.put("page-1", "<html></html>")
    club_row = {**blank_row(schema.CLUBS), "slug": "rochdale", "name": "Rochdale"}
    registry.register(_source(
        "alpha", keys=lambda context: ["page-1"],
        build=lambda cache, club, context: Batch(clubs=[club_row])))

    result = _run(tmp_path, ["collect", "--club", "rochdale", "--dry-run"])

    assert result.exit_code == 0
    assert "Nothing written (--dry-run)." in result.output
    assert "Database rebuilt" not in result.output
    assert _git(tmp_path, "status", "--porcelain", "--", "data").stdout == ""


def test_a_later_source_sees_what_an_earlier_one_just_committed(
        tmp_path, monkeypatch):
    """The whole point: standings need this club's matches already loaded.

    Without a commit and a rebuild between sources, "beta" here would see
    the database exactly as it was before "alpha" ran — because everything
    "alpha" wrote is still sitting uncommitted, and its own write would be
    refused before it ever got a chance to look.
    """
    monkeypatch.setattr(registry, "_REGISTRY", {})
    cache = PageCache(tmp_path / "cache")
    cache.put("alpha-page", "<html></html>")
    cache.put("beta-page", "<html></html>")

    club_row = {**blank_row(schema.CLUBS), "slug": "rochdale", "name": "Rochdale"}
    registry.register(_source(
        "alpha", keys=lambda context: ["alpha-page"],
        build=lambda cache, club, context: Batch(clubs=[club_row])))

    seen_clubs_before_beta = []

    def beta_build(cache, club, context):
        seen_clubs_before_beta.append(
            {row["slug"] for row in context["clubs"]})
        return Batch()

    registry.register(_source(
        "beta", keys=lambda context: ["beta-page"], build=beta_build))

    result = _run(tmp_path, ["collect", "--club", "rochdale"])

    assert result.exit_code == 0
    assert seen_clubs_before_beta == [{"rochdale"}]
    assert "Database rebuilt with the new data." in result.output
    log = _git(tmp_path, "log", "--oneline").stdout
    assert "Collect rochdale from alpha" in log


def test_fetching_a_source_loops_past_a_single_budget(tmp_path, monkeypatch):
    """`collect` must not stop after one budget-limited pass — a club with
    more pages than the budget must still be fully fetched in one run."""
    monkeypatch.setattr(registry, "_REGISTRY", {})
    pages = ["p1", "p2", "p3"]
    registry.register(_source("alpha", keys=lambda context: pages))

    from football import cli_import
    from football.crawl import CrawlResult

    calls = []

    def fake_crawl(outstanding, cache, source, budget):
        calls.append(list(outstanding))
        cache.put(outstanding[0], "<html></html>")  # one page per pass
        return CrawlResult(fetched=1, skipped=0, remaining=len(outstanding) - 1)

    monkeypatch.setattr(cli_import, "crawl", fake_crawl)

    result = _run(tmp_path, ["collect", "--club", "rochdale", "--budget", "1"])

    assert result.exit_code == 0
    assert len(calls) == len(pages)
    assert "alpha: nothing to change" in result.output
