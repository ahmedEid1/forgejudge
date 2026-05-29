from baseconv import from_base, to_base


def test_ten_in_binary_is_most_significant_first():
    # 10 == 0b1010; the buggy code emits the reversed "0101".
    assert to_base(10, 2) == "1010"


def test_decimal_multi_digit_order():
    # 123 must render in normal reading order, not reversed ("321").
    assert to_base(123, 10) == "123"


def test_hex_multi_digit_order():
    # 255 -> "ff" is a palindrome, so use 0x1f2 == 498 to expose ordering.
    assert to_base(498, 16) == "1f2"


def test_round_trip_to_then_from():
    # from_base(to_base(n, b), b) must recover n for every base.
    for n in (1, 2, 10, 255, 1000, 123456):
        for b in (2, 8, 10, 16, 36):
            assert from_base(to_base(n, b), b) == n


def test_round_trip_three_digit_binary():
    # 6 == 0b110; reversed "011" would round-trip to 3, not 6.
    assert to_base(6, 2) == "110"
    assert from_base(to_base(6, 2), 2) == 6
