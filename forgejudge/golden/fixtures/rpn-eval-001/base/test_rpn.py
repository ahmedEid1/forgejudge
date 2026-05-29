import pytest

from rpn import evaluate


def test_single_number():
    assert evaluate("42") == 42.0


def test_addition():
    assert evaluate("3 4 +") == 7.0


def test_multiplication():
    assert evaluate("6 7 *") == 42.0


def test_chained_commutative():
    # ((2 + 3) * 4) = 20
    assert evaluate("2 3 + 4 *") == 20.0


def test_not_enough_operands():
    with pytest.raises(ValueError):
        evaluate("1 +")


def test_invalid_token():
    with pytest.raises(ValueError):
        evaluate("1 2 x")
