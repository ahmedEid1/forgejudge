"""Repair-step helpers: build the edit prompt, extract code, gate bad edits."""

import ast
import re

from forgejudge.types import Task

_FENCE = re.compile(r"```(?:[\w.+-]*)\n(.*?)```", re.DOTALL)

_SYSTEM = (
    "You are an autonomous software-engineering agent. A test is failing. Edit the "
    "SOURCE file so the failing test passes WITHOUT breaking the other tests. Do not "
    "modify any test file. Reply with the COMPLETE corrected contents of the single "
    "file to fix, in one ```python fenced code block, and nothing else."
)


def extract_code(text: str) -> str | None:
    """Return the last fenced code block, or the whole text if it parses as Python."""
    blocks = _FENCE.findall(text)
    if blocks:
        code = blocks[-1]
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
