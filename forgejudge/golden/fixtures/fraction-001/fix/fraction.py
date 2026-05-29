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

    # Normalize the sign so the denominator is always positive: when the
    # denominator is negative, flip both terms so the sign rides on the numerator.
    sign = -1 if den < 0 else 1
    return sign * (num // g), sign * (den // g)
