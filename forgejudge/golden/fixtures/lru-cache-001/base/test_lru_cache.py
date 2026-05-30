from lru_cache import LRUCache


def test_get_and_put():
    c = LRUCache(3)
    c.put("a", 1)
    c.put("b", 2)
    assert c.get("a") == 1
    assert c.get("b") == 2


def test_missing_returns_default():
    c = LRUCache(3)
    assert c.get("x") is None
    assert c.get("x", 0) == 0


def test_overwrite_existing_under_capacity():
    c = LRUCache(3)
    c.put("a", 1)
    c.put("b", 2)
    c.put("a", 10)  # overwrite, still under capacity -> nothing evicted
    assert c.get("a") == 10
    assert c.get("b") == 2
