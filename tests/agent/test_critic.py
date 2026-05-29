"""The critic rejects edits that don't address the failing test and triggers a
regeneration before submit. Router/critic are injected fakes — no LLM key."""

from pathlib import Path

import pytest

from forgejudge.agent.critic import critique
from forgejudge.agent.solver import solve
from forgejudge.golden.build_dataset import source_dir_for
from forgejudge.golden.loader import load_tasks
from forgejudge.harness.grade import grade
from forgejudge.llm.router import Completion

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
TASKS = {t.instance_id: t for t in load_tasks(REPO_ROOT / "golden" / "dataset.jsonl")}
SEMVER = "fixture-semver-001"


def _const(text: str):
    def fn(messages, *, role, run_id):
        return Completion(text=text, tokens_in=5, tokens_out=5, cost_usd=0.0, model="fake")
    return fn


def _sequence(texts: list[str]):
    calls = {"i": 0}

    def fn(messages, *, role, run_id):
        t = texts[min(calls["i"], len(texts) - 1)]
        calls["i"] += 1
        return Completion(text=t, tokens_in=5, tokens_out=5, cost_usd=0.0, model="fake")
    return fn


def test_empty_patch_is_rejected_without_calling_llm():
    def boom(messages, *, role, run_id):
        raise AssertionError("LLM must not be called for an empty patch")

    res = critique(TASKS[SEMVER], "", complete_fn=boom, run_id="c0")
    assert res.approved is False


def test_reject_verdict_is_parsed():
    res = critique(TASKS[SEMVER], "def compare(a,b):\n    return 0\n",
                   complete_fn=_const("REJECT: does not touch the comparison logic"), run_id="c1")
    assert res.approved is False
    assert "REJECT" in res.reason


def test_approve_verdict_is_parsed():
    res = critique(TASKS[SEMVER], "def compare(a,b):\n    return 0\n",
                   complete_fn=_const("APPROVE"), run_id="c2")
    assert res.approved is True


@pytest.mark.slow
def test_solver_regenerates_after_critic_rejection():
    buggy = (source_dir_for(SEMVER) / "base" / "semver.py").read_text()
    gold = (source_dir_for(SEMVER) / "fix" / "semver.py").read_text()
    # First edit is the unchanged buggy file (critic rejects); second is the gold fix.
    edits = _sequence([f"```python\n{buggy}```", f"```python\n{gold}```"])
    critics = _sequence(["REJECT: still has the bug", "APPROVE"])

    res = solve(
        TASKS[SEMVER], run_id="creg", budget_usd=0.1, seed=0, max_steps=4,
        complete_fn=edits, critic_fn=critics,
    )
    assert res.critic_rejections >= 1          # the dud was filtered before testing
    assert res.status == "ok"
    assert grade(TASKS[SEMVER], res.patch).resolved is True
