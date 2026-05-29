"""Regression tests for code extraction from model output (extract_code).

Covers two confirmed defects:
  #12 multi-fence output: a trailing 'usage example' snippet must NOT be
      returned in place of the full corrected file.
  #13 robustness: a truncated (no closing fence) / newline-less / CRLF fence
      should still yield the code instead of None.
"""

from forgejudge.agent.repair import extract_code, is_valid_python

FULL_FILE = "def add(a, b):\n    return a + b\n\n\ndef sub(a, b):\n    return a - b\n"


# ---------------------------------------------------------------------------
# Finding #12 — do not return the LAST fenced block (usage-example snippet)
# ---------------------------------------------------------------------------

def test_multi_fence_prefers_full_file_over_trailing_example():
    text = (
        "Here is the corrected file:\n"
        f"```python\n{FULL_FILE}```\n\n"
        "Example usage:\n"
        "```python\nadd(1, 2)\n```\n"
    )
    code = extract_code(text)
    assert code == FULL_FILE
    # The trailing snippet (also valid Python) must not win.
    assert "add(1, 2)" not in code or "def add" in code
    assert code.strip() != "add(1, 2)"


def test_multi_fence_skips_invalid_trailing_block():
    # A trailing non-python (e.g. shell) block must not be returned.
    text = (
        f"```python\n{FULL_FILE}```\n\n"
        "Run it with:\n"
        "```bash\n$ python add.py --x 1\n```\n"
    )
    assert extract_code(text) == FULL_FILE


def test_first_full_block_wins_when_example_comes_first():
    # Even an example-first ordering should not lose the full file.
    text = (
        "```python\nadd(1, 2)\n```\n\n"
        f"The fix:\n```python\n{FULL_FILE}```\n"
    )
    assert extract_code(text) == FULL_FILE


# ---------------------------------------------------------------------------
# Finding #13 — robustness: truncation / no newline after lang / CRLF
# ---------------------------------------------------------------------------

def test_truncated_output_missing_closing_fence():
    text = "Here is the fix:\n```python\n" + FULL_FILE  # no closing ```
    code = extract_code(text)
    assert code is not None
    assert is_valid_python(code)
    assert "def add" in code
    # The stray opening fence must not leak into the returned code.
    assert "```" not in code


def test_truncated_output_fence_only_no_prose():
    text = "```python\n" + FULL_FILE  # opener + body, truncated before closer
    code = extract_code(text)
    assert code is not None
    assert is_valid_python(code)
    assert "```" not in code


def test_crlf_line_endings_are_tolerated():
    body = FULL_FILE.replace("\n", "\r\n")
    text = "```python\r\n" + body + "```"
    code = extract_code(text)
    assert code is not None
    assert is_valid_python(code)
    assert "def add" in code
    assert "```" not in code


def test_no_newline_after_lang_tag():
    text = "```python def foo():\n    return 1\n```"
    code = extract_code(text)
    assert code is not None
    assert is_valid_python(code)
    assert "def foo" in code
    assert "```" not in code


# ---------------------------------------------------------------------------
# Existing-behaviour guards (single fence / fallback / no code)
# ---------------------------------------------------------------------------

def test_single_fence_roundtrips():
    text = f"```python\n{FULL_FILE}```"
    assert extract_code(text) == FULL_FILE


def test_plain_python_without_fence_falls_back():
    assert extract_code(FULL_FILE) == FULL_FILE


def test_prose_with_no_code_returns_none():
    assert extract_code("I could not find the bug, sorry.") is None


def test_trailing_newline_is_normalised():
    text = "```python\ndef f():\n    return 1```"  # no newline before closer
    code = extract_code(text)
    assert code is not None
    assert code.endswith("\n")
