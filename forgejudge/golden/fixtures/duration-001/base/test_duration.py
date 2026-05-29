from duration import parse_duration


def test_seconds_only():
    assert parse_duration("90s") == 90


def test_zero_seconds():
    assert parse_duration("0s") == 0


def test_multiple_seconds_tokens_sum():
    # The seconds multiplier (1) is correct even on the buggy module.
    assert parse_duration("10s5s") == 15


def test_strips_surrounding_whitespace():
    assert parse_duration("  45s  ") == 45


def test_empty_string_raises():
    import pytest

    with pytest.raises(ValueError):
        parse_duration("")
