"""A tiny semantic-version comparator."""


def compare(a: str, b: str) -> int:
    """Compare two dotted version strings.

    Returns -1 if ``a < b``, 0 if equal, 1 if ``a > b``.
    """
    pa = [int(x) for x in a.split(".")]
    pb = [int(x) for x in b.split(".")]
    n = max(len(pa), len(pb))
    pa += [0] * (n - len(pa))
    pb += [0] * (n - len(pb))
    for x, y in zip(pa, pb):
        if x < y:
            return -1
        if x > y:
            return 1
    return 0
