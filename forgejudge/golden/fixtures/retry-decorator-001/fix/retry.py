"""A retry decorator that re-invokes a function when it raises.

``retry(attempts=N)`` calls the wrapped function up to ``N`` times in total. If
a call raises one of ``exceptions``, the next attempt runs; the value from the
first successful call is returned. If every attempt raises, the exception from
the final attempt propagates. ``on_retry`` (if given) is called with the
1-based attempt number that just failed.
"""

import functools


def retry(attempts: int = 3, exceptions: tuple = (Exception,), on_retry=None):
    if attempts < 1:
        raise ValueError("attempts must be >= 1")

    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            last_exc = None
            for attempt in range(1, attempts + 1):
                try:
                    return func(*args, **kwargs)
                except exceptions as exc:
                    last_exc = exc
                    if on_retry is not None:
                        on_retry(attempt)
            raise last_exc

        return wrapper

    return decorator
