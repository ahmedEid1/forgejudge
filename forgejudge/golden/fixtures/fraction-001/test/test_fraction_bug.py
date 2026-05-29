from fraction import reduce


def test_negative_denominator_moves_sign_to_numerator():
    # 1/-2 == -1/2, and the denominator must come back positive.
    assert reduce(1, -2) == (-1, 2)


def test_negative_denominator_with_reduction():
    # 6/-9 reduces to -2/3 with the sign on the numerator.
    assert reduce(6, -9) == (-2, 3)


def test_both_negative_is_positive():
    # -2/-4 == 1/2: two negatives cancel, denominator positive.
    assert reduce(-2, -4) == (1, 2)


def test_negative_denominator_unit_numerator():
    # -7/-1 == 7/1: both signs negative cancel to a positive integer.
    assert reduce(-7, -1) == (7, 1)


def test_denominator_always_positive():
    # The denominator of the result is never negative.
    for num, den in [(1, -2), (6, -9), (-2, -4), (5, -10), (-7, -1)]:
        _, d = reduce(num, den)
        assert d > 0


def test_zero_numerator_negative_denominator():
    # 0/-5 normalizes to (0, 1): denominator positive, magnitude reduced.
    assert reduce(0, -5) == (0, 1)
