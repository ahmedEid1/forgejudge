from lru_cache import LRUCache


def test_holds_both_at_capacity():
    # A capacity-2 cache must hold BOTH items after two puts; nothing is full yet.
    c = LRUCache(2)
    c.put("a", 1)
    c.put("b", 2)
    assert len(c) == 2
    assert c.get("a") == 1
    assert c.get("b") == 2


def test_keeps_two_most_recent():
    # capacity 2: after a, b, c the two most-recent (b, c) survive, a is evicted.
    c = LRUCache(2)
    c.put("a", 1)
    c.put("b", 2)
    c.put("c", 3)
    assert len(c) == 2
    assert "a" not in c
    assert c.get("b") == 2
    assert c.get("c") == 3


def test_get_refreshes_recency_at_capacity():
    # With the cache full at 2, reading "a" refreshes it so the next insert
    # evicts "b" (the least-recently-used), not "a".
    c = LRUCache(2)
    c.put("a", 1)
    c.put("b", 2)
    assert c.get("a") == 1  # touch "a" -> "b" is now least-recently-used
    c.put("c", 3)           # should evict "b", not "a"
    assert "b" not in c
    assert c.get("a") == 1
    assert c.get("c") == 3
