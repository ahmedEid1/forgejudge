"""Parse a compact duration string like ``1h30m15s`` into total seconds."""

import re

_TOKEN = re.compile(r"(\d+)([hms])")


def parse_duration(s: str) -> int:
    """Return the total number of seconds in a compact duration string.

    Accepts an ordered run of ``<int><unit>`` groups where unit is one of
    ``h`` (hours), ``m`` (minutes) or ``s`` (seconds), e.g. ``"1h30m15s"``,
    ``"45m"`` or ``"90s"``.

    Raises :class:`ValueError` on malformed input.
    """
    text = s.strip()
    if not text:
        raise ValueError(f"empty duration: {s!r}")

    total = 0
    pos = 0
    for match in _TOKEN.finditer(text):
        if match.start() != pos:
            raise ValueError(f"malformed duration: {s!r}")
        pos = match.end()
        value = int(match.group(1))
        unit = match.group(2)
        if unit == "h":
            seconds_per_unit = 3600
        elif unit == "m":
            seconds_per_unit = 60
        else:
            seconds_per_unit = 1
        total = total + value * seconds_per_unit

    if pos != len(text):
        raise ValueError(f"malformed duration: {s!r}")
    return total
