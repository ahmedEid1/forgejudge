from rpn import evaluate


def test_division_is_true_division():
    # "7 2 /" means 7 / 2 = 3.5, not the truncated 3.
    assert evaluate("7 2 /") == 3.5


def test_division_fraction_below_one():
    # "1 4 /" means 1 / 4 = 0.25, not 0.
    assert evaluate("1 4 /") == 0.25


def test_division_keeps_fractional_part():
    # "9 4 /" means 9 / 4 = 2.25, not the truncated 2.
    assert evaluate("9 4 /") == 2.25


def test_mixed_expression_with_division():
    # ((1 + 2) / 4) = 0.75, not 0.
    assert evaluate("1 2 + 4 /") == 0.75
