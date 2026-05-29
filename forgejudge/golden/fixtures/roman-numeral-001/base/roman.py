"""Convert integers to Roman numerals."""


# Value/symbol table, processed from largest to smallest.
_TABLE = [
    (1000, "M"),
    (500, "D"),
    (100, "C"),
    (50, "L"),
    (10, "X"),
    (5, "V"),
    (1, "I"),
]


def to_roman(n: int) -> str:
    """Return the Roman-numeral representation of a positive integer."""
    if not isinstance(n, int) or n <= 0:
        raise ValueError("n must be a positive integer")
    out = []
    remaining = n
    for value, symbol in _TABLE:
        count, remaining = divmod(remaining, value)
        out.append(symbol * count)
    return "".join(out)
