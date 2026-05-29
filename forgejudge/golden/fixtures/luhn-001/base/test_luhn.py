from luhn import is_valid


def test_simple_valid_visa():
    # A 16-digit number that passes the checksum.
    assert is_valid("4111111111111111") is True


def test_short_valid():
    assert is_valid("18") is True


def test_simple_invalid():
    assert is_valid("13") is False


def test_rejects_non_digits():
    assert is_valid("abc123") is False


def test_rejects_too_short():
    assert is_valid("5") is False


def test_rejects_empty():
    assert is_valid("") is False
