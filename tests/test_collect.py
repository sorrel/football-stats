"""`collect` runs fetch then import for a club across every available source.

The point is that it does this by reading the registry rather than a fixed
list, so a source added or withdrawn later changes what `collect` does
without anyone touching this command.
"""

from click.testing import CliRunner

from football import schema, store
from football.cache import PageCache
from football.cli import cli
from football.sources import registry
from football.sources.batch import Batch


def _seed(data_dir):
    store.write_table(data_dir, schema.CLUBS, [])
    store.write_table(data_dir, schema.COMPETITIONS, [])
    store.write_table(data_dir, schema.VENUES, [])
    store.write_matches(data_dir, [])


def _source(name, *, available=True, unavailable_because="", keys=None,
            build=None):
    return registry.Source(
        name=name, covers="test", licence="test",
        keys=keys or (lambda context: []),
        build=build or (lambda cache, club, context: Batch()),
        available=available, unavailable_because=unavailable_because)


def _run(tmp_path, args):
    _seed(tmp_path / "data")
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

    result = _run(tmp_path, ["collect", "--club", "rochdale", "--force"])

    assert result.exit_code == 0
    assert "== alpha ==" in result.output
    assert "No pages cached for alpha" in result.output
    assert "== beta ==" in result.output
    assert "1 of 2 source(s) could not be collected: alpha." in result.output
    assert "Run `football rebuild`" in result.output


def test_every_available_source_that_has_pages_is_imported(
        tmp_path, monkeypatch):
    monkeypatch.setattr(registry, "_REGISTRY", {})
    cache = PageCache(tmp_path / "cache")
    cache.put("page-1", "<html></html>")
    registry.register(_source("alpha", keys=lambda context: ["page-1"]))

    result = _run(tmp_path, ["collect", "--club", "rochdale", "--force"])

    assert result.exit_code == 0
    assert "alpha: nothing to change" in result.output
    assert "could not be collected" not in result.output
    assert "Run `football rebuild`" in result.output


def test_dry_run_never_suggests_a_rebuild(tmp_path, monkeypatch):
    monkeypatch.setattr(registry, "_REGISTRY", {})
    cache = PageCache(tmp_path / "cache")
    cache.put("page-1", "<html></html>")
    registry.register(_source("alpha", keys=lambda context: ["page-1"]))

    result = _run(tmp_path, ["collect", "--club", "rochdale", "--dry-run"])

    assert result.exit_code == 0
    assert "Run `football rebuild`" not in result.output
