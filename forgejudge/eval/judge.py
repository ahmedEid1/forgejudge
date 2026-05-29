"""LLM-as-judge: a SECONDARY, qualitative score for an agent's patch.

The judge produces a discrete 1-5 rubric score (correctness / clarity /
idiomaticity) for a patch. It is *advisory only*: the PRIMARY gate in ForgeJudge
is always deterministic test execution (see :class:`forgejudge.types.GradeResult`
and ``forgejudge.harness.grade``). A patch that fails the tests is unresolved no
matter what the judge thinks; a patch that passes is resolved even if the judge
dislikes its style. The judge score is stored alongside the verdict
(``RunRecord.judge_score``) purely to surface qualitative signal on the
leaderboard, never to decide pass/fail.

Because an LLM judge is itself fallible, we calibrate it against human gold
labels using **Cohen's kappa** (:func:`cohen_kappa`) — chance-corrected
agreement between the judge's scores and a human rater's scores. A kappa near 1.0
means the judge tracks human judgement; a kappa near (or below) 0 means it is no
better than chance and should not be trusted. The calibration format lives in
``golden/judge_gold.jsonl`` (loaded by :func:`load_judge_gold`).

The module-level constant :data:`PRIMARY_GATE` records, in code, that this judge
is NOT the primary gate.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from forgejudge.llm.router import Completion
from forgejudge.llm.router import complete as _router_complete
from forgejudge.types import Task

# The judge is explicitly secondary. The primary, authoritative gate is the
# deterministic FAIL->PASS / PASS->PASS test execution, never this score.
PRIMARY_GATE = "test_execution"

# Discrete rubric bounds.
MIN_SCORE = 1
MAX_SCORE = 5

_SYSTEM = (
    "You are a meticulous senior code reviewer acting as a SECONDARY quality "
    "judge. The patch has ALREADY been graded by automated tests; your score is "
    "advisory and never decides pass/fail. Rate the patch on a single discrete "
    "1-5 rubric covering correctness, clarity, and idiomaticity:\n"
    "  1 = wrong / unreadable, 2 = poor, 3 = acceptable, 4 = good, "
    "5 = excellent and idiomatic.\n"
    "Reply with the score on the first line as 'Score: <N>' (a single integer "
    "1-5), then a one-line rationale."
)


@dataclass
class JudgeScore:
    """The judge's qualitative verdict for one patch.

    ``score`` is a discrete integer in [1, 5]; ``rationale`` is the model's
    free-text justification (or a fixed note for the empty-patch shortcut).
    """

    score: int
    rationale: str


def _parse_score(text: str) -> int:
    """Extract the rubric 1-5 score from the model's reply.

    The system prompt instructs the model to emit ``Score: <N>`` on the first
    line, so we anchor on that label first and only then fall back to looser
    patterns. This avoids capturing an unrelated digit that happens to appear
    *before* the actual score (e.g. "There are 3 issues but overall Score: 5"
    must read 5, not 3).

    Resolution order:
      1. an explicit ``Score: <N>`` / ``score = N`` label (prefer the last such
         match, since a model may restate it),
      2. an ``N/5`` rating,
      3. as a last resort, the first standalone 1-5 digit anywhere.

    Falls back to the minimum score if no 1-5 digit is present at all (a
    non-answer is, for a quality judge, the worst case).
    """
    labelled = re.findall(r"(?im)\bscore\b\s*[:=]?\s*([1-5])\b", text)
    if labelled:
        return int(labelled[-1])
    out_of_five = re.search(r"([1-5])\s*/\s*5\b", text)
    if out_of_five is not None:
        return int(out_of_five.group(1))
    loose = re.search(r"[1-5]", text)
    if loose is None:
        return MIN_SCORE
    return int(loose.group(0))


def judge_patch(
    task: Task,
    patch: str,
    *,
    complete_fn=_router_complete,
    run_id: str,
) -> JudgeScore:
    """Score ``patch`` for ``task`` on the discrete 1-5 quality rubric.

    ``complete_fn`` is injected (the production default is
    :func:`forgejudge.llm.router.complete`; tests pass a fake). An empty or
    whitespace-only patch scores the minimum WITHOUT calling the LLM — there is
    nothing to judge.
    """
    if not patch or not patch.strip():
        return JudgeScore(MIN_SCORE, "empty patch: nothing to judge")

    messages = [
        {"role": "system", "content": _SYSTEM},
        {
            "role": "user",
            "content": (
                f"# Issue\n{task.problem_statement}\n\n"
                f"# Patch (unified diff)\n```diff\n{patch}\n```\n\n"
                "Score (first line 'Score: <1-5>', then a one-line rationale):"
            ),
        },
    ]
    comp: Completion = complete_fn(messages, role="judge", run_id=run_id)
    reply = comp.text.strip()
    return JudgeScore(_parse_score(reply), reply)


def cohen_kappa(rater_a: list[int], rater_b: list[int]) -> float:
    """Cohen's kappa: chance-corrected agreement between two raters.

    ``kappa = (po - pe) / (1 - pe)`` where ``po`` is the observed agreement
    proportion and ``pe`` is the agreement expected by chance from each rater's
    marginal label distribution. Pure stdlib — no sklearn/scipy.

    Returns 1.0 when agreement is perfect and chance agreement is also total
    (i.e. ``1 - pe == 0``), the conventional degenerate-case value. Raises
    ``ValueError`` on mismatched or empty inputs.
    """
    if len(rater_a) != len(rater_b):
        raise ValueError("raters must have the same number of items")
    n = len(rater_a)
    if n == 0:
        raise ValueError("cannot compute kappa over zero items")

    # Observed agreement.
    agree = sum(1 for a, b in zip(rater_a, rater_b, strict=True) if a == b)
    po = agree / n

    # Expected (chance) agreement from the marginal label frequencies.
    labels = set(rater_a) | set(rater_b)
    pe = 0.0
    for label in labels:
        p_a = sum(1 for a in rater_a if a == label) / n
        p_b = sum(1 for b in rater_b if b == label) / n
        pe += p_a * p_b

    denom = 1.0 - pe
    if denom == 0.0:
        # Both raters used a single label identically -> perfect by convention.
        return 1.0 if po == 1.0 else 0.0
    return (po - pe) / denom


def load_judge_gold(path: str | Path) -> list[dict]:
    """Load the human-labelled judge calibration seed set (JSONL).

    Each row is a dict with at least ``instance_id`` and ``human_score`` (and a
    ``patch_kind`` of ``"gold"`` or ``"bad"``). See ``golden/judge_gold.jsonl``.
    """
    path = Path(path)
    rows: list[dict] = []
    for lineno, raw in enumerate(path.read_text().splitlines(), start=1):
        if not raw.strip():
            continue
        try:
            row = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{path}: line {lineno}: invalid JSON: {exc}") from exc
        if "instance_id" not in row or "human_score" not in row:
            raise ValueError(
                f"{path}: line {lineno}: row missing 'instance_id' or 'human_score'"
            )
        rows.append(row)
    return rows
