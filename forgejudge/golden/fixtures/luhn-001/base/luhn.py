"""A Luhn-checksum validator for card / IMEI numbers."""


def is_valid(number: str) -> bool:
    """Return ``True`` iff ``number`` passes the Luhn checksum.

    ``number`` may contain spaces, which are ignored. A string with any
    non-digit (other than spaces) or fewer than two digits is invalid.
    """
    stripped = number.replace(" ", "")
    if len(stripped) < 2 or not stripped.isdigit():
        return False

    digits = [int(c) for c in stripped]
    total = 0
    for i, d in enumerate(digits):
        if i % 2 == 0:
            d = d * 2
        total = total + d
    return total % 10 == 0
