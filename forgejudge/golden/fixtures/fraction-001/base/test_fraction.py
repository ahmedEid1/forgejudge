from fraction import reduce


def test_already_lowest_terms():
    assert reduce(3, 4) == (3, 4)


def test_reduces_common_factor():
    assert reduce(2, 4) == (1, 2)


def test_reduces_larger_common_factor():
    assert reduce(12, 18) == (2, 3)


def test_improper_fraction():
    assert reduce(10, 4) == (5, 2)


def test_integer_value():
    assert reduce(7, 1) == (7, 1)


def test_zero_numerator():
    assert reduce(0, 5) == (0, 1)


def test_zero_denominator_raises():
    import pytest

    with pytest.raises(ZeroDivisionError):
        reduce(1, 0)
