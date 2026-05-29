"""LLM-as-judge (secondary score) + Cohen's kappa calibration.

The judge's ``complete_fn`` is an injected fake here — no LLM key, no network.
These tests pin: robust score parsing, the empty-patch shortcut, the kappa
formula against a hand-computed value, and the secondary-gate documentation.
"""

from pathlib import Path

import pytest

from forgejudge.eval.judge import (
    PRIMARY_GATE,
    JudgeScore,
    cohen_kappa,
    judge_patch,
    load_judge_gold,
)
from forgejudge.golden.loader import load_tasks
from forgejudge.llm.router import Completion

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
TASKS = {t.instance_id: t for t in load_tasks(REPO_ROOT / "golden" / "dataset.jsonl")}
SEMVER = "fixture-semver-001"
JUDGE_GOLD = REPO_ROOT / "golden" / "judge_gold.jsonl"

PATCH = (
    "--- a/semver.py\n+++ b/semver.py\n@@\n-    return 0\n+    return (a > b) - (a < b)\n"
)


def _const(text: str):
    def fn(messages, *, role, run_id):
        assert role == "judge"
        return Completion(text=text, tokens_in=5, tokens_out=5, cost_usd=0.0, model="fake")

    return fn


# --- judge_patch ---------------------------------------------------------------


def test_judge_parses_discrete_score_from_reply():
    res = judge_patch(
        TASKS[SEMVER], PATCH,
        complete_fn=_const("Score: 4\nrationale: correct and idiomatic"),
        run_id="j1",
    )
    assert isinstance(res, JudgeScore)
    assert res.score == 4
    assert "rationale" in res.rationale.lower()


def test_judge_parses_score_in_varied_formats():
    for text, expected in [("5/5 excellent", 5), ("I'd give this a 3.", 3), ("2", 2)]:
        res = judge_patch(TASKS[SEMVER], PATCH, complete_fn=_const(text), run_id="jv")
        assert res.score == expected


def test_judge_anchors_on_score_label_ignoring_earlier_digits():
    """Finding #19: a non-score digit before 'Score:' must not corrupt parsing.

    The system prompt asks for 'Score: <N>' on the first line; the parser must
    anchor on that label, not grab the first 1-5 digit anywhere in the reply.
    """
    cases = [
        ("There are 3 issues but overall Score: 5", 5),
        ("In 2 ways this is good.\nScore: 5", 5),
        ("Score: 4\nThere were 2 minor nits.", 4),
        ("score = 1\nbad: regressed 5 tests", 1),
    ]
    for text, expected in cases:
        res = judge_patch(TASKS[SEMVER], PATCH, complete_fn=_const(text), run_id="ja")
        assert res.score == expected, f"{text!r} -> {res.score}, expected {expected}"


def test_empty_patch_scores_one_without_calling_llm():
    def boom(messages, *, role, run_id):
        raise AssertionError("LLM must not be called for an empty patch")

    res = judge_patch(TASKS[SEMVER], "", complete_fn=boom, run_id="j0")
    assert res.score == 1
    # whitespace-only is also empty
    res2 = judge_patch(TASKS[SEMVER], "   \n  ", complete_fn=boom, run_id="j0b")
    assert res2.score == 1


# --- cohen_kappa ---------------------------------------------------------------


def test_kappa_perfect_agreement_is_one():
    assert cohen_kappa([1, 2, 3, 4], [1, 2, 3, 4]) == 1.0


def test_kappa_total_disagreement_is_non_positive():
    # Perfectly swapped labels: observed agreement 0, expected 0.5 -> kappa = -1.0.
    assert cohen_kappa([1, 1, 2, 2], [2, 2, 1, 1]) <= 0


def test_kappa_known_example_matches_hand_computed():
    # a=[1,2,3,4,5,1], b=[1,2,3,4,1,1]: po=5/6, pe=0.25 -> kappa = (5/6-1/4)/(3/4).
    a = [1, 2, 3, 4, 5, 1]
    b = [1, 2, 3, 4, 1, 1]
    assert cohen_kappa(a, b) == pytest.approx(0.7777777777777778, abs=1e-9)


def test_kappa_single_label_perfect_is_one():
    # Degenerate: both raters used one identical label -> 1 - pe == 0 -> 1.0.
    assert cohen_kappa([3, 3, 3], [3, 3, 3]) == 1.0


def test_kappa_rejects_mismatched_lengths():
    with pytest.raises(ValueError):
        cohen_kappa([1, 2, 3], [1, 2])


# --- documentation: judge is SECONDARY -----------------------------------------


def test_judge_is_documented_as_secondary_gate():
    # The primary gate is deterministic test execution, NOT the LLM judge.
    assert PRIMARY_GATE == "test_execution"
    import forgejudge.eval.judge as judge_mod

    assert "SECONDARY" in judge_mod.__doc__


# --- gold calibration seed set -------------------------------------------------


def test_load_judge_gold_rows_have_required_fields():
    rows = load_judge_gold(JUDGE_GOLD)
    assert len(rows) >= 6
    for row in rows:
        assert "instance_id" in row
        assert "human_score" in row
        assert isinstance(row["human_score"], int)
        assert 1 <= row["human_score"] <= 5
