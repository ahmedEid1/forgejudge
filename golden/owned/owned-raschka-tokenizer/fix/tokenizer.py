"""
tokenizer.py — Chapter 2: Working with text data
=================================================
Implements the simple regex-based tokenizers introduced in §2.2–2.4, a vocab
builder helper, and a thin wrapper around tiktoken for BPE tokenization (§2.5).

Key classes / functions
-----------------------
build_vocab(text)           Build a V2-compatible vocab dict from raw text.
SimpleTokenizerV1           Listing 2.3 — encodes/decodes using a fixed vocab;
                            raises KeyError on out-of-vocab tokens.
SimpleTokenizerV2           Listing 2.4 — maps unknown tokens to <|unk|> and
                            supports the <|endoftext|> separator token.
get_bpe_tokenizer(name)     Thin wrapper returning a tiktoken encoding object
                            (lazy import so the module loads without network I/O
                            when tiktoken is not installed).
"""

import re

# ---------------------------------------------------------------------------
# Tokenization regexes — the book uses two slightly different patterns.
#   * V2 / vocab building (§2.2 p.45 & Listing 2.4): includes colon & semicolon.
#   * V1 encode (Listing 2.3): omits colon & semicolon.
# Splits on the listed punctuation OR ``--`` OR any whitespace; after splitting
# we strip and discard empty items.
# ---------------------------------------------------------------------------
_SPLIT_RE = r"""([,.:;?_!"()\']|--|\s)"""        # V2 / build_vocab (Listing 2.4)
_SPLIT_RE_V1 = r"""([,.?_!"()\']|--|\s)"""        # V1 (Listing 2.3) — no : ;


def _tokenize(text: str, pattern: str = _SPLIT_RE) -> list[str]:
    """Split *text* into tokens using one of the book's regexes (§2.2)."""
    tokens = re.split(pattern, text)
    return [t.strip() for t in tokens if t.strip()]


def build_vocab(text: str) -> dict[str, int]:
    """
    Tokenise *text*, collect unique tokens, sort alphabetically, then append
    the two special tokens ``<|endoftext|>`` and ``<|unk|>`` (in that order)
    so the resulting vocab is compatible with :class:`SimpleTokenizerV2`.

    Parameters
    ----------
    text:
        Raw input text (e.g. the full training corpus or a small sample).

    Returns
    -------
    dict[str, int]
        Mapping of token string → integer token ID.

    Example
    -------
    >>> vocab = build_vocab("Hello, world!")
    >>> "<|unk|>" in vocab
    True
    """
    tokens = _tokenize(text)
    all_tokens = sorted(set(tokens))
    all_tokens.extend(["<|endoftext|>", "<|unk|>"])
    return {token: idx for idx, token in enumerate(all_tokens)}


# ---------------------------------------------------------------------------
# SimpleTokenizerV1 — Listing 2.3
# ---------------------------------------------------------------------------

class SimpleTokenizerV1:
    """
    Regex-based tokenizer with a fixed vocabulary (§2.3, Listing 2.3).

    Raises ``KeyError`` when encoding a token that is absent from the vocab.
    Use :class:`SimpleTokenizerV2` if you need ``<|unk|>`` fallback.

    Parameters
    ----------
    vocab:
        A ``{token: id}`` mapping, typically produced by :func:`build_vocab`
        (without the special tokens) or constructed manually.

    Example
    -------
    >>> vocab = build_vocab("Hello, world. This is a test.")
    >>> tok = SimpleTokenizerV1(vocab)
    >>> ids = tok.encode("Hello, world.")
    >>> tok.decode(ids)
    'Hello, world.'
    """

    def __init__(self, vocab: dict[str, int]) -> None:
        self.str_to_int: dict[str, int] = vocab
        self.int_to_str: dict[int, str] = {i: s for s, i in vocab.items()}

    def encode(self, text: str) -> list[int]:
        """
        Tokenise *text* and map tokens to integer IDs.

        Raises
        ------
        KeyError
            If any token is not present in the vocabulary.
        """
        tokens = _tokenize(text, _SPLIT_RE_V1)  # Listing 2.3 regex (no : ;)
        return [self.str_to_int[t] for t in tokens]

    def decode(self, ids: list[int]) -> str:
        """
        Convert a list of token IDs back to a human-readable string.

        Spaces before punctuation characters are removed so that the output
        reads naturally (e.g. ``"Hello ,"`` becomes ``"Hello,"``).
        """
        text = " ".join(self.int_to_str[i] for i in ids)
        # Remove spaces that were inserted before punctuation during join.
        text = re.sub(r'\s+([,.?!"()\'])', r'\1', text)
        return text


# ---------------------------------------------------------------------------
# SimpleTokenizerV2 — Listing 2.4
# ---------------------------------------------------------------------------

class SimpleTokenizerV2:
    """
    Regex-based tokenizer with ``<|unk|>`` fallback and ``<|endoftext|>``
    separator support (§2.4, Listing 2.4).

    Unknown tokens are replaced by ``<|unk|>`` during encoding rather than
    raising an error.  Both special tokens must be present in *vocab*; use
    :func:`build_vocab` to generate a compatible vocab.

    Parameters
    ----------
    vocab:
        A ``{token: id}`` mapping that **must** include ``<|unk|>`` and
        ``<|endoftext|>``.  Typically produced by :func:`build_vocab`.

    Example
    -------
    >>> sample = "the quick brown fox"
    >>> vocab = build_vocab(sample)
    >>> tok = SimpleTokenizerV2(vocab)
    >>> tok.decode(tok.encode("unknown_word"))
    '<|unk|>'
    """

    def __init__(self, vocab: dict[str, int]) -> None:
        self.str_to_int: dict[str, int] = vocab
        self.int_to_str: dict[int, str] = {i: s for s, i in vocab.items()}

    def encode(self, text: str) -> list[int]:
        """
        Tokenise *text* and map tokens to integer IDs.  Unknown tokens are
        mapped to the ``<|unk|>`` ID.
        """
        tokens = _tokenize(text)
        tokens = [
            t if t in self.str_to_int else "<|unk|>" for t in tokens
        ]
        return [self.str_to_int[t] for t in tokens]

    def decode(self, ids: list[int]) -> str:
        """
        Convert a list of token IDs back to a human-readable string.

        Spaces before punctuation characters are removed so that the output
        reads naturally.
        """
        text = " ".join(self.int_to_str[i] for i in ids)
        # Remove spaces before punctuation.
        text = re.sub(r'\s+([,.:;?!"()\'])', r'\1', text)
        return text


# ---------------------------------------------------------------------------
# BPE wrapper — §2.5
# ---------------------------------------------------------------------------

def get_bpe_tokenizer(name: str = "gpt2"):
    """
    Return a ``tiktoken`` encoding object for *name* (default ``"gpt2"``).

    ``tiktoken`` is imported lazily so that this module can be imported in
    environments where ``tiktoken`` is not installed (the import will only
    fail when this function is actually called).

    The returned object exposes the same ``.encode()`` / ``.decode()``
    interface as the simple tokenizers above and supports the
    ``allowed_special`` parameter required to handle ``<|endoftext|>``.

    Parameters
    ----------
    name:
        The tiktoken encoding name.  ``"gpt2"`` gives a 50,257-token BPE
        vocabulary identical to the one used in GPT-2 / GPT-3.

    Returns
    -------
    tiktoken.Encoding

    Example
    -------
    >>> enc = get_bpe_tokenizer("gpt2")
    >>> enc.decode(enc.encode("Hello, world!"))
    'Hello, world!'
    """
    import tiktoken  # lazy import — avoids hard dep at module level
    return tiktoken.get_encoding(name)
