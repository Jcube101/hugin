from unittest.mock import patch

from cache import MISSING, TTLCache


class TestTTLCache:

    def test_get_returns_missing_when_absent(self):
        assert TTLCache(ttl=60).get("x") is MISSING

    def test_set_then_get(self):
        c = TTLCache(ttl=60)
        c.set("x", {"a": 1})
        assert c.get("x") == {"a": 1}

    def test_none_is_a_real_cached_value(self):
        # Keyword lookups cache "no such TMDb tag" as None
        c = TTLCache(ttl=60)
        c.set("x", None)
        assert c.get("x") is None

    def test_entries_expire(self):
        c = TTLCache(ttl=60)
        with patch("cache.time.monotonic", return_value=1000.0):
            c.set("x", 1)
        with patch("cache.time.monotonic", return_value=1059.0):
            assert c.get("x") == 1
        with patch("cache.time.monotonic", return_value=1060.0):
            assert c.get("x") is MISSING
        assert len(c) == 0

    def test_oldest_entry_evicted_past_maxsize(self):
        c = TTLCache(ttl=60, maxsize=2)
        c.set("a", 1)
        c.set("b", 2)
        c.set("c", 3)
        assert c.get("a") is MISSING
        assert c.get("b") == 2 and c.get("c") == 3

    def test_reading_an_entry_keeps_it_fresh(self):
        c = TTLCache(ttl=60, maxsize=2)
        c.set("a", 1)
        c.set("b", 2)
        c.get("a")          # a is now the most recently used
        c.set("c", 3)       # so b is evicted, not a
        assert c.get("a") == 1
        assert c.get("b") is MISSING

    def test_clear(self):
        c = TTLCache(ttl=60)
        c.set("a", 1)
        c.clear()
        assert len(c) == 0
