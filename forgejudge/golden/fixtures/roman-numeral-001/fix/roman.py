"""Convert integers to Roman numerals."""


# Value/symbol table, processed from largest to smallest.
# Includes the subtractive pairs (4, 9, 40, 90, 400, 900).
_TABLE = [
    (1000, "M"),
    (900, "CM"),
    (500, "D"),
    (400, "CD"),
    (100, "C"),
    (90, "XC"),
    (50, "L"),
    (40, "XL"),
    (10, "X"),
    (9, "IX"),
    (5, "V"),
    (4, "IV"),
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
