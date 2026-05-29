"""Summary statistics for a window of numbers: mean and sample variance."""


def mean(xs: list[float]) -> float:
    """Return the arithmetic mean of ``xs``.

    Raises ``ValueError`` on an empty sequence.
    """
    if len(xs) < 1:
        raise ValueError("mean requires at least one value")
    return sum(xs) / len(xs)


def sample_variance(xs: list[float]) -> float:
    """Return the *sample* variance of ``xs`` (Bessel-corrected).

    Divides the sum of squared deviations by ``n - 1`` (degrees of freedom).
    Raises ``ValueError`` when fewer than two values are supplied.
    """
    if len(xs) < 1:
        raise ValueError("sample_variance requires at least two values")
    m = mean(xs)
    n = len(xs)
    total = sum((x - m) ** 2 for x in xs)
    return total / n
