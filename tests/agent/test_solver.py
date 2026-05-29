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
    # Accepts **kwargs so the solver can forward `seed` (and any future kwargs).
    def fn(messages, *, role, run_id, **kwargs):
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
    def costly(messages, *, role, run_id, **kwargs):
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


def _p2p_empty_task():
    """The semver task, but with NO pre-existing PASS_TO_PASS tests (legal metadata)."""
    return TASKS[SEMVER].model_copy(update={"pass_to_pass": []})


# ---- #14: an empty PASS_TO_PASS list must still be solvable in hidden mode ----

@pytest.mark.slow
def test_hidden_mode_resolves_when_pass_to_pass_is_empty():
    # With pass_to_pass=[] the run_nodeids_status result is {}, which the old
    # `_all_pass({})` rejected -> the success gate was structurally unreachable and
    # the loop burned the whole budget. "No regression" must be vacuously true.
    task = _p2p_empty_task()
    res = solve(task, run_id="p2p-empty", budget_usd=0.1, seed=0, max_steps=3,
                complete_fn=_fake_returning(_wrap(_gold())))
    assert res.status == "ok"
    assert res.steps == 1  # accepted on the first edit, did not burn the budget


@pytest.mark.slow
def test_empty_p2p_feedback_has_no_trailing_broke_tests_string():
    # When there is nothing to regress the loop must not fall through to the
    # "Your change broke existing tests: " (empty list) feedback branch. With the
    # gate fixed it resolves immediately, so a non-fix never reaches that branch.
    task = _p2p_empty_task()
    res = solve(task, run_id="p2p-empty2", budget_usd=0.1, seed=0, max_steps=2,
                complete_fn=_fake_returning(_wrap(_buggy())))
    # The buggy file has no regression either, so it is accepted (status ok) rather
    # than looping with a degenerate "broke existing tests:" feedback.
    assert res.status == "ok"


# ---- #30: critic spend must be folded into the reported cost ----

@pytest.mark.slow
def test_critic_cost_is_counted_in_total():
    # The edit completion is free; only the critic call costs money. If critic spend
    # were dropped (as it was), cost_usd would read 0.0 and undercount real spend.
    def free_edit(messages, *, role, run_id, **kwargs):
        return Completion(text=_wrap(_gold()), tokens_in=10, tokens_out=10, cost_usd=0.0,
                          model="fake")

    def paid_critic(messages, *, role, run_id, **kwargs):
        return Completion(text="APPROVE", tokens_in=5, tokens_out=3, cost_usd=0.02, model="fake")

    res = solve(TASKS[SEMVER], run_id="critic-cost", budget_usd=0.1, seed=0, max_steps=2,
                complete_fn=free_edit, critic_fn=paid_critic)
    assert res.status == "ok"
    assert res.cost_usd == pytest.approx(0.02)
    assert res.tokens_in >= 5 and res.tokens_out >= 3  # critic tokens folded in too


# ---- #31: garbage / no-code-block responses are counted ----

@pytest.mark.slow
def test_no_code_block_responses_are_counted():
    # Prose with no fenced block and no parseable code -> extract_code returns None.
    # The run must surface this so a budget wasted on non-answers is distinguishable
    # from a clean run (it is NOT a syntax-revert, so reverted_edits stays 0).
    res = solve(TASKS[SEMVER], run_id="garbage", budget_usd=0.1, seed=0, max_steps=2,
                complete_fn=_fake_returning("I cannot help with that, sorry."))
    assert res.no_code_responses == 2
    assert res.reverted_edits == 0
    assert res.status == "budget_exceeded"


def test_fallback_target_agrees_with_localizer_on_tests_dir():
    # localize and the solver fallback must classify a `tests/` package identically;
    # the old solver predicate only recognised the literal "test" directory, so
    # `tests/helpers.py` disagreed (localize: test, solver-fallback: source).
    from forgejudge.agent.localize import _is_test_file
    from forgejudge.agent.solver import _is_test_path

    for rel in ("tests/helpers.py", "tests/conftest.py", "pkg/tests/util.py"):
        assert _is_test_path(rel) is True
        assert _is_test_path(rel) == _is_test_file(Path(rel))
    # And a plain source file is still editable under both predicates.
    assert _is_test_path("pkg/core.py") is False


# ---- #3: the seed must reach the model call (not just the trace attribute) ----

def test_seed_is_forwarded_to_the_completion_call():
    seen = {}

    def capture(messages, *, role, run_id, **kwargs):
        seen.setdefault(role, []).append(kwargs.get("seed", "MISSING"))
        return Completion(text=_wrap(_gold()), tokens_in=1, tokens_out=1, cost_usd=0.0,
                          model="fake")

    solve(TASKS[SEMVER], run_id="seed-thread", budget_usd=0.1, seed=7, max_steps=1,
          complete_fn=capture)
    assert seen["edit"] == [7]  # the edit call received seed=7, not the default/MISSING
