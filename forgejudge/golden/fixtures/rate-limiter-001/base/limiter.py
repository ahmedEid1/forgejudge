"""A fixed-window rate limiter.

``RateLimiter(max_calls, window)`` allows at most ``max_calls`` successful
calls within any ``window``-second window. ``allow(now)`` returns ``True`` if
the call is permitted at timestamp ``now`` (and records it), ``False`` if the
caller has hit the limit for the current window.
"""


class RateLimiter:
    def __init__(self, max_calls: int, window: float):
        if max_calls <= 0:
            raise ValueError("max_calls must be positive")
        if window <= 0:
            raise ValueError("window must be positive")
        self.max_calls = max_calls
        self.window = window
        self._window_start = None
        self._count = 0

    def allow(self, now: float) -> bool:
        # Start (or restart) the window if this is the first call or the
        # current window has fully elapsed.
        if self._window_start is None or now - self._window_start >= self.window:
            self._window_start = now
            self._count = 0

        if self._count > self.max_calls:
            return False
        self._count += 1
        return True
