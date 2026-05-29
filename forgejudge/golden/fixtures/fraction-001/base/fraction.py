"""Reduce a fraction to lowest terms with a normalized sign."""


def reduce(num: int, den: int) -> tuple[int, int]:
    """Reduce ``num/den`` to lowest terms.

    The denominator of the result is always positive; any negative sign is
    carried by the numerator. Raises ``ZeroDivisionError`` when ``den == 0``.
    """
    if den == 0:
        raise ZeroDivisionError("denominator is zero")

    # Greatest common divisor of the magnitudes via the Euclidean algorithm.
    a = num if num >= 0 else -num
    b = den if den >= 0 else -den
    while b != 0:
        a, b = b, a % b
    g = a if a != 0 else 1

    # BUG: the sign is never normalized. The denominator keeps whatever sign it
    # arrived with, so a negative denominator survives instead of being carried
    # onto the numerator -- e.g. reduce(1, -2) returns (1, -2), not (-1, 2).
    return num // g, den // g
