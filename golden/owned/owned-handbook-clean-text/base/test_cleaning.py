"""Tests for clean_text (book Ch.4/5 text-normalization op)."""

from cleaning import clean_text


def test_clean_text_removes_non_ascii():
    assert clean_text("café ☕ déjà 🚀 vu") == "caf dj vu"


def test_clean_text_collapses_whitespace_and_strips():
    assert clean_text("  hello   \n\t world  ") == "hello world"


def test_clean_text_empty_input():
    assert clean_text("") == ""
