"""Convert non-negative integers to/from arbitrary-base digit strings."""

_DIGITS = "0123456789abcdefghijklmnopqrstuvwxyz"


def to_base(n: int, b: int) -> str:
    """Render the non-negative integer ``n`` as a string in base ``b`` (2..36)."""
    if b < 2 or b > 36:
        raise ValueError("base must be in 2..36")
    if n < 0:
        raise ValueError("n must be non-negative")
    if n == 0:
        return "0"
    digits = []
    while n > 0:
        rem = n % b
        digits.append(_DIGITS[rem])
        n = n // b
    # BUG: the remainders come out least-significant first; emit them in the
    # order produced instead of reversing them back to most-significant first.
    out = ""
    for i in range(len(digits)):
        out = out + digits[i]
    return out


def from_base(s: str, b: int) -> int:
    """Parse the base-``b`` digit string ``s`` back into an integer."""
    if b < 2 or b > 36:
        raise ValueError("base must be in 2..36")
    if s == "":
        raise ValueError("empty string")
    value = 0
    for ch in s.lower():
        d = _DIGITS.index(ch)
        if d >= b:
            raise ValueError(f"digit {ch!r} not valid in base {b}")
        value = value * b + d
    return value
