"""A tiny semantic-version comparator."""


def compare(a: str, b: str) -> int:
    """Compare two dotted version strings.

    Returns -1 if ``a < b``, 0 if equal, 1 if ``a > b``.
    """
    pa = a.split(".")
    pb = b.split(".")
    for x, y in zip(pa, pb):
        if x < y:
            return -1
        if x > y:
            return 1
    if len(pa) < len(pb):
        return -1
    if len(pa) > len(pb):
        return 1
    return 0
