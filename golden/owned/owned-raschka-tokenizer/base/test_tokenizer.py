"""
Tests for tokenizer (Chapter 2).

All tests run without network access — a small inline text sample is used
to build the vocabulary.
"""

import pytest

from tokenizer import (
    build_vocab,
    SimpleTokenizerV1,
    SimpleTokenizerV2,
)

# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

SAMPLE_TEXT = (
    "Hello, world. This is a test! "
    "Do you like tea? I do. "
    "The quick brown fox jumps over the lazy dog."
)


@pytest.fixture()
def vocab():
    """Vocabulary built from SAMPLE_TEXT (includes <|unk|>, <|endoftext|>)."""
    return build_vocab(SAMPLE_TEXT)


@pytest.fixture()
def v1(vocab):
    return SimpleTokenizerV1(vocab)


@pytest.fixture()
def v2(vocab):
    return SimpleTokenizerV2(vocab)


# ---------------------------------------------------------------------------
# build_vocab
# ---------------------------------------------------------------------------

class TestBuildVocab:
    def test_contains_special_tokens(self, vocab):
        assert "<|unk|>" in vocab
        assert "<|endoftext|>" in vocab

    def test_special_tokens_at_end(self, vocab):
        """<|endoftext|> and <|unk|> should be the two largest IDs."""
        max_id = max(vocab.values())
        assert vocab["<|unk|>"] == max_id
        assert vocab["<|endoftext|>"] == max_id - 1

    def test_all_values_unique(self, vocab):
        ids = list(vocab.values())
        assert len(ids) == len(set(ids))

    def test_ids_are_contiguous(self, vocab):
        ids = sorted(vocab.values())
        assert ids == list(range(len(ids)))


# ---------------------------------------------------------------------------
# SimpleTokenizerV1 — round-trip encode → decode
# ---------------------------------------------------------------------------

class TestSimpleTokenizerV1:
    def test_encode_returns_ints(self, v1):
        ids = v1.encode("Hello, world.")
        assert isinstance(ids, list)
        assert all(isinstance(i, int) for i in ids)

    def test_round_trip(self, v1):
        """Decode(encode(text)) should reproduce the original text."""
        text = "Hello, world."
        assert v1.decode(v1.encode(text)) == text

    def test_punctuation_no_leading_space(self, v1):
        """decode() must not insert a space before punctuation."""
        ids = v1.encode("Hello, world.")
        decoded = v1.decode(ids)
        assert " ," not in decoded
        assert " ." not in decoded

    def test_unknown_word_raises(self, v1):
        """V1 should raise KeyError for out-of-vocab tokens."""
        with pytest.raises(KeyError):
            v1.encode("xyzzy_not_in_vocab")

    def test_known_sentence(self, v1):
        ids = v1.encode("The quick brown fox")
        assert len(ids) == 4
        decoded = v1.decode(ids)
        assert decoded == "The quick brown fox"


# ---------------------------------------------------------------------------
# SimpleTokenizerV2 — unknown tokens and <|endoftext|>
# ---------------------------------------------------------------------------

class TestSimpleTokenizerV2:
    def test_unknown_word_maps_to_unk(self, v2, vocab):
        ids = v2.encode("xyzzy_not_in_vocab")
        unk_id = vocab["<|unk|>"]
        assert unk_id in ids

    def test_endoftext_token_survives_round_trip(self, v2, vocab):
        """<|endoftext|> must be encodable and decodable."""
        eot_id = vocab["<|endoftext|>"]
        ids = v2.encode("<|endoftext|>")
        assert eot_id in ids
        decoded = v2.decode(ids)
        assert "<|endoftext|>" in decoded

    def test_mixed_known_unknown(self, v2, vocab):
        """Unknown words become <|unk|>; known words keep their IDs."""
        unk_id = vocab["<|unk|>"]
        ids = v2.encode("Hello, zorblax")
        # "Hello" is known, "zorblax" is unknown
        assert unk_id in ids
        assert ids[0] == vocab["Hello"]

    def test_no_keyerror_on_unknown(self, v2):
        """V2 must never raise KeyError, even for all-unknown input."""
        try:
            v2.encode("zzz yyy xxx www")
        except KeyError:
            pytest.fail("SimpleTokenizerV2.encode raised KeyError unexpectedly")

    def test_round_trip_known_text(self, v2):
        text = "The quick brown fox."
        assert v2.decode(v2.encode(text)) == text

    def test_separator_between_texts(self, v2):
        """Demonstrate the book's §2.4 usage: joining texts with <|endoftext|>."""
        text1 = "Hello, world."
        text2 = "The quick brown fox."
        combined = " <|endoftext|> ".join([text1, text2])
        ids = v2.encode(combined)
        decoded = v2.decode(ids)
        assert "<|endoftext|>" in decoded


# ---------------------------------------------------------------------------
# V1 vs V2 regex divergence — Listing 2.3 omits ":" and ";"; Listing 2.4 keeps them
# ---------------------------------------------------------------------------

class TestV1V2RegexDivergence:
    def test_v2_splits_colon_and_semicolon(self):
        """V2 (Listing 2.4) treats ':' and ';' as standalone tokens."""
        vocab = build_vocab("Hello: world; bye")
        assert ":" in vocab and ";" in vocab
        v2 = SimpleTokenizerV2(vocab)
        ids = v2.encode("Hello: world")
        assert vocab[":"] in ids  # colon emitted as its own token

    def test_v1_keeps_colon_attached(self):
        """V1 (Listing 2.3) does NOT split on ':', so 'Hello:' is one token."""
        vocab = {"Hello:": 0, "world": 1, "<|endoftext|>": 2, "<|unk|>": 3}
        v1 = SimpleTokenizerV1(vocab)
        assert v1.encode("Hello: world") == [0, 1]

    def test_v1_does_not_split_colon_with_v2_vocab(self):
        """With a V2-style vocab (':' separate), V1 fails because it produces
        the unsplit token 'Hello:' — proof that V1 leaves ':' attached."""
        vocab = build_vocab("Hello: world")
        v1 = SimpleTokenizerV1(vocab)
        with pytest.raises(KeyError):
            v1.encode("Hello: world")
