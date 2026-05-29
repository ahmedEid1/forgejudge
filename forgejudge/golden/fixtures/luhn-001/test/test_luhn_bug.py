from luhn import is_valid


def test_accepts_known_valid_number():
    # The classic Luhn worked example; this number is valid.
    # The buggy version doubles the wrong digits and rejects it.
    assert is_valid("79927398713") is True


def test_accepts_valid_card_number():
    # A 16-digit card-style number that genuinely passes the checksum.
    assert is_valid("4532015112830366") is True


def test_rejects_number_that_only_passes_when_doubling_from_left():
    # "8301" does NOT satisfy the Luhn checksum, but a validator that doubles
    # from the leftmost digit accepts it. A correct validator must reject it.
    assert is_valid("8301") is False


def test_subtract_nine_on_doubled_digit():
    # "59" is valid: doubling the second-from-right digit (5 -> 10 -> 1) and
    # adding the check digit (9) gives 10, which is divisible by 10. A validator
    # that skips the "subtract 9 when the double exceeds 9" step gets this wrong.
    assert is_valid("59") is True


def test_ignores_spaces_in_valid_number():
    # Grouping spaces must not change the verdict for a valid number.
    assert is_valid("4532 0151 1283 0366") is True
