from roman import to_roman


def test_one():
    assert to_roman(1) == "I"


def test_three():
    assert to_roman(3) == "III"


def test_ten():
    assert to_roman(10) == "X"


def test_additive_thirty_seven():
    # 37 = XXX + V + II, no subtractive notation involved
    assert to_roman(37) == "XXXVII"


def test_two_thousand():
    assert to_roman(2000) == "MM"


def test_rejects_zero():
    import pytest

    with pytest.raises(ValueError):
        to_roman(0)
