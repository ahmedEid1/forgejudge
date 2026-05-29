from rpn import evaluate


def test_subtraction_order():
    # "5 3 -" means 5 - 3 = 2, not 3 - 5
    assert evaluate("5 3 -") == 2.0


def test_division_order():
    # "8 2 /" means 8 / 2 = 4, not 2 / 8
    assert evaluate("8 2 /") == 4.0


def test_mixed_expression():
    # ((10 - 2) / 4) = 2
    assert evaluate("10 2 - 4 /") == 2.0


def test_subtraction_negative_result():
    # "3 10 -" means 3 - 10 = -7
    assert evaluate("3 10 -") == -7.0
