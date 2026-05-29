from limiter import RateLimiter


def test_blocks_call_over_limit():
    rl = RateLimiter(max_calls=3, window=10)
    assert rl.allow(now=0) is True
    assert rl.allow(now=1) is True
    assert rl.allow(now=2) is True
    # The 4th call in the same window must be rejected.
    assert rl.allow(now=3) is False


def test_exactly_max_calls_then_block():
    rl = RateLimiter(max_calls=1, window=10)
    assert rl.allow(now=0) is True
    # With max_calls=1 the very next call in-window must be blocked.
    assert rl.allow(now=1) is False


def test_block_persists_until_window_resets():
    rl = RateLimiter(max_calls=2, window=10)
    assert rl.allow(now=0) is True
    assert rl.allow(now=1) is True
    # Over the limit: subsequent in-window calls stay blocked.
    assert rl.allow(now=2) is False
    assert rl.allow(now=3) is False
    # New window: allowed again.
    assert rl.allow(now=10) is True
