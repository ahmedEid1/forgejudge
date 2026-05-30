"""A small fixed-capacity LRU (least-recently-used) cache."""

from collections import OrderedDict


class LRUCache:
    """Maps keys to values, evicting the least-recently-used entry when full.

    A key counts as "used" both when it is written with :meth:`put` and when it
    is read with :meth:`get`. When capacity is exceeded the entry that has gone
    the longest without being used is evicted.
    """

    def __init__(self, capacity: int) -> None:
        if capacity <= 0:
            raise ValueError("capacity must be positive")
        self.capacity = capacity
        self._store: OrderedDict[object, object] = OrderedDict()

    def get(self, key, default=None):
        if key not in self._store:
            return default
        self._store.move_to_end(key)
        return self._store[key]

    def put(self, key, value) -> None:
        if key in self._store:
            self._store.move_to_end(key)
        self._store[key] = value
        if len(self._store) >= self.capacity:
            self._store.popitem(last=False)

    def __len__(self) -> int:
        return len(self._store)

    def __contains__(self, key) -> bool:
        return key in self._store

    def keys(self):
        """Keys from least- to most-recently-used."""
        return list(self._store.keys())
