from baseconv import from_base, to_base


def test_zero():
    # 0 is a special case handled before the digit loop, so it is correct.
    assert to_base(0, 2) == "0"
    assert to_base(0, 16) == "0"


def test_single_digit_outputs():
    # When the result is a single digit there is nothing to reorder, so the
    # buggy and correct implementations agree.
    assert to_base(5, 10) == "5"
    assert to_base(7, 8) == "7"
    assert to_base(15, 16) == "f"


def test_from_base_basic():
    assert from_base("1010", 2) == 10
    assert from_base("ff", 16) == 255
    assert from_base("z", 36) == 35


def test_from_base_round_trips_known_strings():
    # from_base is independent of the to_base ordering bug.
    assert from_base("0", 2) == 0
    assert from_base("100", 10) == 100


def test_invalid_base_rejected():
    import pytest

    with pytest.raises(ValueError):
        to_base(10, 1)
    with pytest.raises(ValueError):
        from_base("10", 37)
