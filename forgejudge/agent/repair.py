"""Repair-step helpers: build the edit prompt, extract code, gate bad edits."""

import ast
import re

from forgejudge.types import Task

# Match a fenced block tolerantly: optional language tag, optional newline after
# it (some models put code on the opener line), and an OPTIONAL closing fence so a
# truncated (cut off near max_tokens) response is still usable. CRLF is normalised
# before matching.  ``\Z`` lets the final block run to the end of the text.
_FENCE = re.compile(r"```[\w.+-]*[ \t]*\n?(.*?)(?:```|\Z)", re.DOTALL)

_SYSTEM = (
    "You are an autonomous software-engineering agent. A test is failing. Edit the "
    "SOURCE file so the failing test passes WITHOUT breaking the other tests. Do not "
    "modify any test file. Reply with the COMPLETE corrected contents of the single "
    "file to fix, in one ```python fenced code block, and nothing else."
)


def extract_code(text: str) -> str | None:
    """Extract the corrected source file from a model reply.

    Models are asked for one ```python block but routinely append a short second
    snippet (e.g. a usage example), so taking the LAST block silently overwrites
    the file with a one-liner. Instead pick the block most likely to be the full
    file: the longest block that parses as Python, falling back to the longest
    block overall. The matcher also tolerates a missing closing fence (truncated
    output), a fence with no newline after the language tag, and CRLF endings.
    """
    blocks = [b.strip("\r\n") for b in _FENCE.findall(text.replace("\r\n", "\n"))]
    blocks = [b for b in blocks if b.strip()]
    if blocks:
        parseable = [b for b in blocks if is_valid_python(b)]
        code = max(parseable or blocks, key=len)
        return code if code.endswith("\n") else code + "\n"
    stripped = text.strip()
    if stripped and is_valid_python(stripped):
        return stripped + "\n"
    return None


def is_valid_python(src: str) -> bool:
    """True iff ``src`` parses (the flake8-style edit gate's core check)."""
    try:
        ast.parse(src)
        return True
    except SyntaxError:
        return False


def build_edit_messages(
    task: Task,
    target_path: str,
    target_src: str,
    failing_tests: str,
    feedback: str = "",
) -> list[dict]:
    """Construct the chat messages for one repair step."""
    user = (
        f"# Issue\n{task.problem_statement}\n\n"
        f"# Failing test(s)\n```python\n{failing_tests}\n```\n\n"
        f"# File to fix: {target_path}\n```python\n{target_src}\n```\n"
    )
    if feedback:
        user += f"\n# Previous attempt feedback\n{feedback}\n"
    user += f"\nReturn the complete corrected contents of {target_path}."
    return [{"role": "system", "content": _SYSTEM}, {"role": "user", "content": user}]
