import pytest

from limiter import RateLimiter


def test_first_call_allowed():
    rl = RateLimiter(max_calls=3, window=10)
    assert rl.allow(now=0) is True


def test_calls_within_limit_allowed():
    rl = RateLimiter(max_calls=3, window=10)
    # The first three calls in the window must all be permitted.
    assert rl.allow(now=0) is True
    assert rl.allow(now=1) is True
    assert rl.allow(now=2) is True


def test_window_resets_after_elapsed():
    rl = RateLimiter(max_calls=2, window=10)
    assert rl.allow(now=0) is True
    assert rl.allow(now=1) is True
    # A fresh window opens once `window` seconds have elapsed.
    assert rl.allow(now=10) is True
    assert rl.allow(now=11) is True


def test_rejects_invalid_max_calls():
    with pytest.raises(ValueError):
        RateLimiter(max_calls=0, window=10)


def test_rejects_invalid_window():
    with pytest.raises(ValueError):
        RateLimiter(max_calls=3, window=0)
