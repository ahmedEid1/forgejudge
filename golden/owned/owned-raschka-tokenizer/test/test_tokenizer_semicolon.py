"""Regression tests for SimpleTokenizerV2.decode with semicolons.

The V2 tokenizer (Listing 2.4) splits on ``;`` during encoding, so a semicolon
becomes its own token. On decode the join inserts a space before every token,
and the cleanup pass must remove the space that precedes a semicolon — exactly
as it does for other punctuation (``, . : ? !``). These tests round-trip text
containing semicolons and assert the natural spacing is restored.
"""

from tokenizer import build_vocab, SimpleTokenizerV2


def _v2(text):
    return SimpleTokenizerV2(build_vocab(text))


def test_decode_removes_space_before_semicolon():
    text = "Hello; world"
    v2 = _v2(text)
    decoded = v2.decode(v2.encode(text))
    assert " ;" not in decoded


def test_round_trip_text_with_semicolon():
    text = "Hello; world; bye"
    v2 = _v2(text)
    assert v2.decode(v2.encode(text)) == text


def test_semicolon_attaches_to_preceding_word():
    text = "one; two; three"
    v2 = _v2(text)
    decoded = v2.decode(v2.encode(text))
    assert "one;" in decoded
    assert "two;" in decoded
