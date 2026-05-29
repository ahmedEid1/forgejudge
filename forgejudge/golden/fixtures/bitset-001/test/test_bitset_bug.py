from bitset import clear_bit, popcount, test_bit


def test_clear_bit_clears_set_bit():
    # Clearing bit 1 of 0b111 must yield 0b101 == 5, not turn more bits on.
    assert clear_bit(0b111, 1) == 0b101


def test_clear_bit_only_touches_target():
    # Clearing bit 0 of 0b10 leaves bit 1 alone and clears nothing extra.
    assert clear_bit(0b10, 0) == 0b10
    # Clearing the only set bit yields zero.
    assert clear_bit(0b10, 1) == 0


def test_clear_bit_does_not_affect_neighbor():
    # Clearing bit i must not clear bit i+1 (guards an off-by-one shift).
    assert clear_bit(0b110, 1) == 0b100


def test_test_bit_reports_set_bits():
    assert test_bit(0b1, 0) is True
    assert test_bit(0b100, 2) is True


def test_test_bit_reports_unset_bits():
    assert test_bit(0b100, 0) is False
    assert test_bit(0b100, 1) is False


def test_popcount_counts_adjacent_bits():
    # 0b11 has two adjacent 1-bits; a stride-2 scan would miss one.
    assert popcount(0b11) == 2
    assert popcount(0b1010) == 2


def test_popcount_all_ones():
    assert popcount(0b1111) == 4
    assert popcount(255) == 8
