"""Bit utilities on non-negative integers."""


def popcount(n: int) -> int:
    """Return the number of 1-bits in the non-negative integer ``n``."""
    count = 0
    while n > 0:
        count += n & 1
        n >>= 1
    return count


def set_bit(n: int, i: int) -> int:
    """Return ``n`` with bit ``i`` set to 1."""
    return n | (1 << i)


def clear_bit(n: int, i: int) -> int:
    """Return ``n`` with bit ``i`` cleared to 0."""
    return n & ~(1 << i)


def test_bit(n: int, i: int) -> bool:
    """Return ``True`` iff bit ``i`` of ``n`` is set."""
    return (n >> i) & 1 == 1
