from lru_cache import LRUCache


def test_get_and_put():
    c = LRUCache(2)
    c.put("a", 1)
    c.put("b", 2)
    assert c.get("a") == 1
    assert c.get("b") == 2


def test_missing_returns_default():
    c = LRUCache(2)
    assert c.get("x") is None
    assert c.get("x", 0) == 0


def test_evicts_when_over_capacity():
    c = LRUCache(2)
    c.put("a", 1)
    c.put("b", 2)
    c.put("c", 3)  # evicts "a", the least-recently-used
    assert "a" not in c
    assert c.get("b") == 2
    assert c.get("c") == 3


def test_put_updates_recency():
    c = LRUCache(2)
    c.put("a", 1)
    c.put("b", 2)
    c.put("a", 10)  # re-writing "a" makes "b" the least-recently-used
    c.put("c", 3)   # evicts "b"
    assert "b" not in c
    assert c.get("a") == 10
