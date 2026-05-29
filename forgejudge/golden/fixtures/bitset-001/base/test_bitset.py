from bitset import popcount, set_bit


def test_set_bit_low():
    # Setting an unset low bit turns it on.
    assert set_bit(0, 0) == 1


def test_set_bit_higher():
    # Setting bit 3 of an empty word gives 0b1000 == 8.
    assert set_bit(0, 3) == 8


def test_set_bit_idempotent():
    # Setting an already-set bit leaves the value unchanged.
    assert set_bit(0b101, 0) == 0b101


def test_popcount_zero():
    assert popcount(0) == 0


def test_popcount_single_bit():
    # A power of two has exactly one 1-bit.
    assert popcount(1) == 1
