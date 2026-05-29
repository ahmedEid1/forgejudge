"""The single-agent solve loop: localize -> repair -> validate, with a step/cost
budget and a syntax edit-gate. The router is injected (a fake), so these tests
need no LLM key.

Visible-test mode (show_failing_test=True) is used to exercise the loop
mechanics; hidden mode (the default) is the credible SWE-bench setup where the
oracle is hidden and grade() is authoritative."""

from pathlib import Path

import pytest

from forgejudge.agent.solver import solve
from forgejudge.golden.build_dataset import source_dir_for
from forgejudge.golden.loader import load_tasks
from forgejudge.harness.grade import grade
from forgejudge.llm.router import Completion

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
TASKS = {t.instance_id: t for t in load_tasks(REPO_ROOT / "golden" / "dataset.jsonl")}
SEMVER = "fixture-semver-001"


def _fake_returning(text: str):
    def fn(messages, *, role, run_id):
        return Completion(text=text, tokens_in=20, tokens_out=20, cost_usd=0.0, model="fake")
    return fn


def _wrap(code: str) -> str:
    return f"Here is the fix:\n```python\n{code}```\n"


def _gold() -> str:
    return (source_dir_for(SEMVER) / "fix" / "semver.py").read_text()


def _buggy() -> str:
    return (source_dir_for(SEMVER) / "base" / "semver.py").read_text()


# ---- visible-test mode: loop mechanics ----

@pytest.mark.slow
def test_solve_with_gold_fix_resolves():
    res = solve(TASKS[SEMVER], run_id="t1", budget_usd=0.1, seed=0, max_steps=3,
                show_failing_test=True, complete_fn=_fake_returning(_wrap(_gold())))
    assert res.status == "ok"
    assert res.resolved_in_loop is True
    assert "semver.py" in res.patch
    assert grade(TASKS[SEMVER], res.patch).resolved is True


@pytest.mark.slow
def test_budget_exhausted_when_never_fixed():
    res = solve(TASKS[SEMVER], run_id="t2", budget_usd=0.1, seed=0, max_steps=2,
                show_failing_test=True, complete_fn=_fake_returning(_wrap(_buggy())))
    assert res.status == "budget_exceeded"
    assert res.resolved_in_loop is False


@pytest.mark.slow
def test_syntax_broken_edit_is_reverted():
    broken = "def compare(a, b)\n    return 0\n"  # missing colon -> SyntaxError
    res = solve(TASKS[SEMVER], run_id="t3", budget_usd=0.1, seed=0, max_steps=2,
                show_failing_test=True, complete_fn=_fake_returning(_wrap(broken)))
    assert res.reverted_edits >= 1
    assert res.status == "budget_exceeded"
    assert "def compare(a, b)\n" not in res.patch


@pytest.mark.slow
def test_cost_budget_stops_the_loop():
    def costly(messages, *, role, run_id):
        return Completion(text=_wrap(_buggy()), tokens_in=20, tokens_out=20, cost_usd=0.05,
                          model="fake")

    res = solve(TASKS[SEMVER], run_id="t4", budget_usd=0.06, seed=0, max_steps=99,
                show_failing_test=True, complete_fn=costly)
    assert res.status == "budget_exceeded"
    assert res.steps <= 3  # stopped on cost, not on max_steps


# ---- hidden-test mode (default): grade() is authoritative ----

@pytest.mark.slow
def test_hidden_mode_gold_fix_resolves_by_grade():
    res = solve(TASKS[SEMVER], run_id="h1", budget_usd=0.1, seed=0, max_steps=3,
                complete_fn=_fake_returning(_wrap(_gold())))
    assert res.status == "ok"
    assert res.resolved_in_loop is False  # the agent cannot see the hidden oracle
    assert grade(TASKS[SEMVER], res.patch).resolved is True  # but the patch truly resolves


@pytest.mark.slow
def test_hidden_mode_nonfix_is_submitted_but_unresolved():
    # The buggy file keeps PASS_TO_PASS green, so the agent submits it — but the
    # hidden oracle (grade) correctly rules it unresolved.
    res = solve(TASKS[SEMVER], run_id="h2", budget_usd=0.1, seed=0, max_steps=2,
                complete_fn=_fake_returning(_wrap(_buggy())))
    assert res.status == "ok"
    assert grade(TASKS[SEMVER], res.patch).resolved is False
