"""Critic / verifier pass: a cheap reviewer that runs BEFORE the (expensive) test
execution. If a proposed edit plainly does not address the failing test, the
critic rejects it and the loop regenerates — saving a full test run on a dud.
"""

from dataclasses import dataclass

from forgejudge.llm.router import Completion
from forgejudge.types import Task

_SYSTEM = (
    "You are a strict code reviewer. You are shown an issue, the failing test, and a "
    "PROPOSED new version of a source file. Decide whether the proposal plausibly makes "
    "the failing test pass without breaking others. Answer with exactly 'APPROVE' or "
    "'REJECT: <one-line reason>' on the first line."
)


@dataclass
class CritiqueResult:
    approved: bool
    reason: str


def critique(
    task: Task,
    proposed: str,
    failing_tests: str = "",
    *,
    complete_fn,
    run_id: str,
) -> CritiqueResult:
    """Review a proposed source revision. Empty proposals are rejected outright."""
    if not proposed or not proposed.strip():
        return CritiqueResult(False, "empty patch addresses nothing")

    messages = [
        {"role": "system", "content": _SYSTEM},
        {
            "role": "user",
            "content": (
                f"# Issue\n{task.problem_statement}\n\n"
                f"# Failing test(s)\n```python\n{failing_tests}\n```\n\n"
                f"# Proposed source\n```python\n{proposed}\n```\n\n"
                "Verdict (APPROVE or REJECT: reason):"
            ),
        },
    ]
    comp: Completion = complete_fn(messages, role="critic", run_id=run_id)
    verdict = comp.text.strip()
    approved = verdict.upper().lstrip().startswith("APPROVE")
    return CritiqueResult(approved, verdict)
