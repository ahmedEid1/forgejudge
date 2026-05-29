"""The guarded live playground rejects free-form/abusive input: pre-vetted tasks
only, per-IP rate limit, fail-closed token budget, Turnstile when configured.
Requires the optional 'playground' extra (fastapi)."""

from pathlib import Path

import pytest

pytest.importorskip("fastapi")

from fastapi.testclient import TestClient  # noqa: E402

from forgejudge.agent.solver import SolveResult  # noqa: E402
from forgejudge.golden.build_dataset import load_solutions  # noqa: E402
from forgejudge.golden.loader import load_tasks  # noqa: E402
from playground_api.app import create_app  # noqa: E402

pytestmark = pytest.mark.playground

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
TASKS = {t.instance_id: t for t in load_tasks(REPO_ROOT / "golden" / "dataset.jsonl")}
GOLD = load_solutions(REPO_ROOT / "golden" / "solutions.jsonl")
SEMVER = "fixture-semver-001"


def _fake_solve(task, *, run_id, budget_usd, seed):
    return SolveResult(patch=GOLD[task.instance_id], status="ok", steps=1, cost_usd=0.0,
                       resolved_in_loop=False, trace_url="https://lf/x", tokens_in=500, tokens_out=200)


def _client(**kw):
    app = create_app(solve_fn=_fake_solve, tasks={SEMVER: TASKS[SEMVER]}, **kw)
    return TestClient(app)


def test_unknown_task_is_rejected():
    r = _client().post("/api/solve", json={"task_id": "free-form-prompt"})
    assert r.status_code == 400


def test_pre_vetted_task_resolves():
    r = _client().post("/api/solve", json={"task_id": SEMVER})
    assert r.status_code == 200 and r.json()["resolved"] is True


def test_per_ip_rate_limit():
    client = _client(rate_limit=2)
    codes = [client.post("/api/solve", json={"task_id": SEMVER}).status_code for _ in range(4)]
    assert codes.count(429) >= 1  # the 2/hr window is exceeded


async def _reject(tok, ip):
    return False


def test_turnstile_required_when_configured():
    c = _client(require_turnstile=True, turnstile_verify=_reject)
    r = c.post("/api/solve", json={"task_id": SEMVER})
    assert r.status_code == 403


def test_daily_token_budget_fail_closes():
    c = _client(daily_budget=1)
    c.app.state.tokens_today = 10**9  # already over budget
    r = c.post("/api/solve", json={"task_id": SEMVER})
    assert r.status_code == 503
