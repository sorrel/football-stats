import pytest

from football.cache import PageCache


def test_put_then_get_round_trips(tmp_path):
    cache = PageCache(tmp_path)
    cache.put("season/2026", "<html>hello</html>")
    assert cache.get("season/2026") == "<html>hello</html>"


def test_has_is_false_before_and_true_after(tmp_path):
    cache = PageCache(tmp_path)
    assert not cache.has("season/2026")
    cache.put("season/2026", "<html></html>")
    assert cache.has("season/2026")


def test_a_key_with_slashes_does_not_escape_the_cache_root(tmp_path):
    cache = PageCache(tmp_path)
    cache.put("../../etc/passwd", "nope")
    assert not (tmp_path.parent.parent / "etc" / "passwd").exists()
    assert cache.get("../../etc/passwd") == "nope"


def test_the_manifest_records_when_each_page_was_fetched(tmp_path):
    cache = PageCache(tmp_path)
    cache.put("season/2026", "<html></html>")
    assert cache.fetched_at("season/2026") is not None
    assert cache.fetched_at("season/1999") is None


def test_the_manifest_survives_a_new_cache_object(tmp_path):
    PageCache(tmp_path).put("season/2026", "<html></html>")
    assert PageCache(tmp_path).has("season/2026")


def test_getting_a_missing_page_raises(tmp_path):
    with pytest.raises(KeyError):
        PageCache(tmp_path).get("season/2026")
