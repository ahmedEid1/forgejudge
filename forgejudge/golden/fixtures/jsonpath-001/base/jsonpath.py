"""A minimal dotted-path resolver for nested dict/list structures.

Supports keys joined by ``.`` and integer list indices in brackets, e.g.
``"items[0].name"`` or ``"user.address.city"``. If any segment cannot be
resolved, the supplied ``default`` is returned.
"""

import re

_INDEX = re.compile(r"\[(\d+)\]")


def _tokenize(path: str) -> list:
    tokens: list = []
    for part in path.split("."):
        # split a segment like "items[0][1]" into "items", 0, 1
        name, *rest = _INDEX.split(part)
        if name:
            tokens.append(name)
        for chunk in rest:
            if chunk.isdigit():
                tokens.append(int(chunk))
    return tokens


def get(data, path: str, default=None):
    """Resolve ``path`` against ``data``; return ``default`` if not found."""
    cur = data
    for tok in _tokenize(path):
        if isinstance(tok, int):
            if not isinstance(cur, list) or tok >= len(cur):
                return default
            cur = cur[tok]
        else:
            if not isinstance(cur, dict) or tok not in cur:
                return default
            cur = cur[tok]
        # stop early if we hit a "missing" value
        if not cur:
            return default
    return cur
