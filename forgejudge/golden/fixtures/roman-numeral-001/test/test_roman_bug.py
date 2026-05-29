from roman import to_roman


def test_four():
    # 4 must be IV, not IIII
    assert to_roman(4) == "IV"


def test_nine():
    # 9 must be IX, not VIIII
    assert to_roman(9) == "IX"


def test_forty_nine():
    # 49 = XL + IX
    assert to_roman(49) == "XLIX"


def test_nineteen_ninety_four():
    # 1994 = M + CM + XC + IV
    assert to_roman(1994) == "MCMXCIV"
