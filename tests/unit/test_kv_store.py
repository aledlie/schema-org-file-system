"""Functional tests for src/storage/kv_store.py (KeyValueStorage).

Covers basic get/set/delete/exists, TTL handling (lazy expiry, ttl/expire/
persist), batch mget/mset, counters, glob key matching, cursor-based scan,
hash operations, cleanup/flush, and info stats.

Expired-key paths are exercised by setting a negative ttl_seconds, which
places expires_at in the past without sleeping or monkeypatching the clock.
"""

from pathlib import Path

import pytest

from src.storage.kv_store import KeyValueStorage, get_kv_store


@pytest.fixture
def kv(tmp_path: Path) -> KeyValueStorage:
    return KeyValueStorage(str(tmp_path / "kv.db"))


def _ttl(kv: KeyValueStorage, key: str) -> int:
    """``ttl()`` narrowed: it returns None for a missing key, but every caller
    below just set an expiry, so None is a test failure rather than a case."""
    remaining = kv.ttl(key)
    assert remaining is not None
    return remaining


class TestBasicOperations:
    @pytest.mark.parametrize(
        "value",
        ["hello", 42, 3.14, True, {"a": 1, "b": [2, 3]}, ["x", "y"], None],
    )
    def test_set_get_roundtrip(self, kv: KeyValueStorage, value):
        assert kv.set("k", value) is True
        assert kv.get("k") == value

    def test_get_missing_returns_default(self, kv: KeyValueStorage):
        assert kv.get("nope") is None
        assert kv.get("nope", default="fallback") == "fallback"

    def test_set_overwrites_existing(self, kv: KeyValueStorage):
        kv.set("k", "first")
        kv.set("k", {"now": "second"})
        assert kv.get("k") == {"now": "second"}

    def test_namespace_isolation(self, kv: KeyValueStorage):
        kv.set("k", "cache-val", namespace=kv.NAMESPACE_CACHE)
        kv.set("k", "config-val", namespace=kv.NAMESPACE_CONFIG)
        assert kv.get("k", namespace=kv.NAMESPACE_CACHE) == "cache-val"
        assert kv.get("k", namespace=kv.NAMESPACE_CONFIG) == "config-val"
        assert kv.get("k", namespace=kv.NAMESPACE_STATS) is None

    def test_delete_existing_key(self, kv: KeyValueStorage):
        kv.set("k", "v")
        assert kv.delete("k") is True
        assert kv.get("k") is None

    def test_delete_missing_key(self, kv: KeyValueStorage):
        assert kv.delete("nope") is False

    def test_exists(self, kv: KeyValueStorage):
        assert kv.exists("k") is False
        kv.set("k", "v")
        assert kv.exists("k") is True

    def test_persistence_across_instances(self, tmp_path: Path):
        db = str(tmp_path / "shared.db")
        KeyValueStorage(db).set("k", "v")
        assert KeyValueStorage(db).get("k") == "v"


class TestTTL:
    def test_get_expired_key_returns_default(self, kv: KeyValueStorage):
        kv.set("k", "v", ttl_seconds=-1)
        assert kv.get("k", default="gone") == "gone"

    def test_expired_key_is_lazily_deleted(self, kv: KeyValueStorage):
        kv.set("k", "v", ttl_seconds=-1)
        kv.get("k")
        assert kv.info()["total_keys"] == 0

    def test_exists_expired_key(self, kv: KeyValueStorage):
        kv.set("k", "v", ttl_seconds=-1)
        assert kv.exists("k") is False
        assert kv.info()["total_keys"] == 0

    def test_ttl_remaining(self, kv: KeyValueStorage):
        kv.set("k", "v", ttl_seconds=60)
        assert 55 <= _ttl(kv, "k") <= 60

    def test_ttl_no_expiry_returns_minus_one(self, kv: KeyValueStorage):
        kv.set("k", "v")
        assert kv.ttl("k") == -1

    def test_ttl_missing_key_returns_none(self, kv: KeyValueStorage):
        assert kv.ttl("nope") is None

    def test_ttl_expired_key_returns_zero(self, kv: KeyValueStorage):
        kv.set("k", "v", ttl_seconds=-100)
        assert kv.ttl("k") == 0

    def test_expire_sets_ttl_on_permanent_key(self, kv: KeyValueStorage):
        kv.set("k", "v")
        assert kv.expire("k", 60) is True
        assert 55 <= _ttl(kv, "k") <= 60

    def test_expire_missing_key(self, kv: KeyValueStorage):
        assert kv.expire("nope", 60) is False

    def test_persist_removes_ttl(self, kv: KeyValueStorage):
        kv.set("k", "v", ttl_seconds=60)
        assert kv.persist("k") is True
        assert kv.ttl("k") == -1

    def test_persist_missing_key(self, kv: KeyValueStorage):
        assert kv.persist("nope") is False

    def test_set_without_ttl_clears_previous_expiry(self, kv: KeyValueStorage):
        kv.set("k", "v", ttl_seconds=60)
        kv.set("k", "v2")
        assert kv.ttl("k") == -1


class TestBatchOperations:
    def test_mget_returns_present_keys_only(self, kv: KeyValueStorage):
        kv.set("a", 1)
        kv.set("b", 2)
        assert kv.mget(["a", "b", "missing"]) == {"a": 1, "b": 2}

    def test_mget_omits_and_deletes_expired(self, kv: KeyValueStorage):
        kv.set("live", 1)
        kv.set("dead", 2, ttl_seconds=-1)
        assert kv.mget(["live", "dead"]) == {"live": 1}
        assert kv.info()["total_keys"] == 1

    def test_mget_empty_namespace(self, kv: KeyValueStorage):
        assert kv.mget(["a", "b"]) == {}

    def test_mset_sets_all_keys(self, kv: KeyValueStorage):
        assert kv.mset({"a": 1, "b": "two"}) is True
        assert kv.get("a") == 1
        assert kv.get("b") == "two"

    def test_mset_applies_ttl(self, kv: KeyValueStorage):
        kv.mset({"a": 1, "b": 2}, ttl_seconds=60)
        assert 55 <= _ttl(kv, "a") <= 60
        assert 55 <= _ttl(kv, "b") <= 60


class TestCounters:
    def test_incr_creates_counter(self, kv: KeyValueStorage):
        assert kv.incr("hits") == 1
        assert kv.get("hits", namespace=kv.NAMESPACE_STATS) == 1

    def test_incr_existing_counter(self, kv: KeyValueStorage):
        kv.incr("hits")
        assert kv.incr("hits", amount=5) == 6

    def test_decr(self, kv: KeyValueStorage):
        kv.incr("hits", amount=10)
        assert kv.decr("hits") == 9
        assert kv.decr("hits", amount=4) == 5

    def test_decr_can_go_negative(self, kv: KeyValueStorage):
        assert kv.decr("balance", amount=3) == -3

    def test_incrby_float_creates_counter(self, kv: KeyValueStorage):
        assert kv.incrby_float("cost", 0.5) == 0.5

    def test_incrby_float_existing_counter(self, kv: KeyValueStorage):
        kv.incrby_float("cost", 0.5)
        assert kv.incrby_float("cost", 1.25) == pytest.approx(1.75)

    def test_incrby_float_over_int_value(self, kv: KeyValueStorage):
        kv.incr("mixed", amount=2)
        assert kv.incrby_float("mixed", 0.5, namespace=kv.NAMESPACE_STATS) == pytest.approx(2.5)


class TestKeysAndScan:
    def test_keys_wildcard_returns_all(self, kv: KeyValueStorage):
        kv.mset({"a": 1, "b": 2, "c": 3})
        assert sorted(kv.keys()) == ["a", "b", "c"]

    def test_keys_glob_star(self, kv: KeyValueStorage):
        kv.mset({"user:1": 1, "user:2": 2, "order:1": 3})
        assert sorted(kv.keys("user:*")) == ["user:1", "user:2"]

    def test_keys_glob_question_mark(self, kv: KeyValueStorage):
        kv.mset({"k1": 1, "k2": 2, "k10": 3})
        assert sorted(kv.keys("k?")) == ["k1", "k2"]

    def test_keys_scoped_to_namespace(self, kv: KeyValueStorage):
        kv.set("a", 1, namespace=kv.NAMESPACE_CACHE)
        kv.set("b", 2, namespace=kv.NAMESPACE_CONFIG)
        assert kv.keys(namespace=kv.NAMESPACE_CONFIG) == ["b"]

    def test_scan_empty(self, kv: KeyValueStorage):
        assert kv.scan() == (0, [])

    def test_scan_single_page(self, kv: KeyValueStorage):
        kv.mset({"a": 1, "b": 2})
        cursor, keys = kv.scan(count=10)
        assert cursor == 0
        assert sorted(keys) == ["a", "b"]

    def test_scan_paginates_until_exhausted(self, kv: KeyValueStorage):
        kv.mset({f"k{i}": i for i in range(7)})
        seen = []
        cursor = 0
        pages = 0
        while True:
            cursor, keys = kv.scan(count=3, cursor=cursor)
            seen.extend(keys)
            pages += 1
            if cursor == 0:
                break
        assert pages == 3
        assert sorted(seen) == sorted(f"k{i}" for i in range(7))

    def test_scan_with_match(self, kv: KeyValueStorage):
        kv.mset({"user:1": 1, "user:2": 2, "order:1": 3})
        _, keys = kv.scan(match="user:*", count=10)
        assert sorted(keys) == ["user:1", "user:2"]


class TestHashOperations:
    def test_hset_hget(self, kv: KeyValueStorage):
        assert kv.hset("file:1", "size", 1024) is True
        assert kv.hget("file:1", "size") == 1024

    def test_hget_missing_field(self, kv: KeyValueStorage):
        assert kv.hget("file:1", "nope") is None

    def test_hgetall(self, kv: KeyValueStorage):
        kv.hset("file:1", "size", 1024)
        kv.hset("file:1", "mime", "image/png")
        kv.hset("file:2", "size", 99)
        assert kv.hgetall("file:1") == {"size": 1024, "mime": "image/png"}

    def test_hgetall_empty(self, kv: KeyValueStorage):
        assert kv.hgetall("nothing") == {}

    def test_hdel(self, kv: KeyValueStorage):
        kv.hset("file:1", "size", 1024)
        kv.hset("file:1", "mime", "image/png")
        assert kv.hdel("file:1", "size", "mime", "missing") == 2
        assert kv.hgetall("file:1") == {}


class TestCleanup:
    def test_cleanup_expired_removes_only_expired(self, kv: KeyValueStorage):
        kv.set("live", 1)
        kv.set("dead1", 2, ttl_seconds=-1)
        kv.set("dead2", 3, ttl_seconds=-1)
        assert kv.cleanup_expired() == 2
        assert kv.get("live") == 1

    def test_cleanup_expired_noop(self, kv: KeyValueStorage):
        kv.set("live", 1)
        assert kv.cleanup_expired() == 0

    def test_flush_namespace(self, kv: KeyValueStorage):
        kv.mset({"a": 1, "b": 2}, namespace=kv.NAMESPACE_CACHE)
        kv.set("keep", 3, namespace=kv.NAMESPACE_CONFIG)
        assert kv.flush_namespace(kv.NAMESPACE_CACHE) == 2
        assert kv.get("a") is None
        assert kv.get("keep", namespace=kv.NAMESPACE_CONFIG) == 3

    def test_flush_all(self, kv: KeyValueStorage):
        kv.set("a", 1, namespace=kv.NAMESPACE_CACHE)
        kv.set("b", 2, namespace=kv.NAMESPACE_CONFIG)
        assert kv.flush_all() == 2
        assert kv.info()["total_keys"] == 0


class TestUtility:
    @pytest.mark.parametrize(
        "value,expected",
        [
            (True, "bool"),
            (7, "int"),
            (1.5, "float"),
            ("s", "string"),
            ({"a": 1}, "json"),
            ([1, 2], "json"),
            (None, "json"),
        ],
    )
    def test_get_value_type(self, kv: KeyValueStorage, value, expected):
        assert kv._get_value_type(value) == expected

    def test_info_counts(self, kv: KeyValueStorage):
        kv.set("a", 1, namespace=kv.NAMESPACE_CACHE)
        kv.set("b", 2, namespace=kv.NAMESPACE_CONFIG)
        kv.set("dead", 3, namespace=kv.NAMESPACE_CACHE, ttl_seconds=-1)
        info = kv.info()
        assert info["total_keys"] == 3
        assert info["by_namespace"] == {"cache": 2, "config": 1}
        assert info["expired_keys"] == 1

    def test_info_empty_store(self, kv: KeyValueStorage):
        assert kv.info() == {"total_keys": 0, "by_namespace": {}, "expired_keys": 0}

    def test_get_kv_store_convenience(self, tmp_path: Path):
        store = get_kv_store(str(tmp_path / "conv.db"))
        assert isinstance(store, KeyValueStorage)
        store.set("k", "v")
        assert store.get("k") == "v"
