"""Regression tests: stray markup must become a word boundary, not vanish.

``clean_text`` strips a small set of markup/bracket characters. When such a
character sits *between* two words (e.g. ``"foo#bar"``), removing it must not
glue the words together — the result has to stay tokenizable as two separate
words. The same ``clean_text`` runs on both the ingested documents and the
retrieval-time query, so a wrong word boundary here silently corrupts both
sides of the RAG pipeline identically.
"""

from cleaning import clean_text


def test_markup_between_words_becomes_space():
    # '#' separates two words; after cleaning they must remain distinct.
    assert clean_text("foo#bar") == "foo bar"


def test_pipe_between_words_becomes_space():
    assert clean_text("alpha|beta") == "alpha beta"


def test_multiple_markup_chars_do_not_collapse_words():
    # A run of markup chars between words still yields exactly one space.
    assert clean_text("left**>>right") == "left right"


def test_markup_glued_to_words_preserves_word_count():
    # Backticks are glued directly to the words (no surrounding spaces): the
    # cleaned text must still split into the four distinct words.
    cleaned = clean_text("use `code`blocks here")
    assert cleaned.split() == ["use", "code", "blocks", "here"]
