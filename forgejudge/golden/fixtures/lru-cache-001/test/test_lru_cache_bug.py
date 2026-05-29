from lru_cache import LRUCache


def test_get_refreshes_recency():
    # Reading "a" should make it recently-used, so the next insert evicts "b".
    c = LRUCache(2)
    c.put("a", 1)
    c.put("b", 2)
    assert c.get("a") == 1   # touch "a" -> "b" is now least-recently-used
    c.put("c", 3)            # should evict "b", not "a"
    assert "b" not in c
    assert c.get("a") == 1
    assert c.get("c") == 3


def test_get_moves_key_to_end():
    c = LRUCache(3)
    c.put("a", 1)
    c.put("b", 2)
    c.put("c", 3)
    c.get("a")  # "a" becomes most-recently-used
    assert c.keys() == ["b", "c", "a"]
