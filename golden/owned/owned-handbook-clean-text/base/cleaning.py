"""``clean_text`` — the shared text-normalization operation (book Ch.4/5).

All nine cleaning handlers funnel through this one function (the strategy pattern
makes per-category cleaning a one-line swap later). The book defers the full list
of steps to Ch.5's instruction-dataset section; the core, documented behaviour is:

* drop characters that aren't safe ASCII (emojis, exotic unicode), since they add
  noise and bloat the vocabulary,
* collapse runs of whitespace into single spaces and strip the ends,
* remove a small set of stray markup/bracket characters the book mentions.

These are deliberately conservative — the point is reproducibility between the
ingestion and retrieval paths (the *same* ``clean_text`` must run on the user
query at retrieval time, or you get train/serve skew).
"""

from __future__ import annotations

import re

# Characters the book strips out as markup/structural noise.
_UNWANTED_CHARS_RE = re.compile(r"[{}[\]\\#*`>|]")
_MULTISPACE_RE = re.compile(r"\s+")


def clean_text(text: str) -> str:
    """Normalize ``text``: drop non-ASCII, strip stray markup, collapse spaces."""
    if not text:
        return ""

    # Remove non-ASCII (emojis / exotic unicode). encode/decode is the book's
    # trick: ASCII-encode ignoring errors, then decode back.
    text = text.encode("ascii", "ignore").decode("ascii")

    # Strip stray markup/bracket characters.
    text = _UNWANTED_CHARS_RE.sub("", text)

    # Collapse whitespace runs into single spaces and trim the ends.
    text = _MULTISPACE_RE.sub(" ", text)

    return text.strip()
