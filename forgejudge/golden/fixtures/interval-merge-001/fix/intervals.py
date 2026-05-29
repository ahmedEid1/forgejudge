"""Merge a list of closed integer intervals.

An interval is a ``(start, end)`` tuple with ``start <= end``. ``merge`` returns
a new sorted list where every set of overlapping or touching intervals has been
combined into one. Closed intervals that share only an endpoint (e.g. ``(1, 3)``
and ``(3, 5)``) are considered to overlap and are merged into ``(1, 5)``.
"""


def merge(intervals: list) -> list:
    """Return the merged, sorted list of intervals."""
    if not intervals:
        return []
    ordered = sorted(intervals, key=lambda iv: (iv[0], iv[1]))
    merged = [tuple(ordered[0])]
    for start, end in ordered[1:]:
        last_start, last_end = merged[-1]
        if start <= last_end:
            # overlapping or touching -> extend the current interval
            merged[-1] = (last_start, max(last_end, end))
        else:
            merged.append((start, end))
    return merged
