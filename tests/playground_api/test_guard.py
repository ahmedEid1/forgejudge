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


def test_rate_limit_is_per_forwarded_ip_not_global():
    """#9: behind the HF reverse proxy the real client IP arrives in
    X-Forwarded-For. Two distinct external IPs must land in distinct buckets,
    so the per-IP window cannot collapse into one global bucket."""
    client = _client(rate_limit=1)
    # IP A exhausts its single-request window.
    a1 = client.post("/api/solve", json={"task_id": SEMVER},
                     headers={"X-Forwarded-For": "203.0.113.1"})
    a2 = client.post("/api/solve", json={"task_id": SEMVER},
                     headers={"X-Forwarded-For": "203.0.113.1"})
    # A different external IP must still be allowed — separate bucket.
    b1 = client.post("/api/solve", json={"task_id": SEMVER},
                     headers={"X-Forwarded-For": "198.51.100.7"})
    assert a1.status_code == 200
    assert a2.status_code == 429  # same IP, window full
    assert b1.status_code == 200  # different IP, own window


def test_xff_uses_leftmost_client_entry():
    """#9: when X-Forwarded-For carries a proxy chain, the *left-most* entry
    (the real client) is used for keying, not the appended proxy hop."""
    client = _client(rate_limit=1)
    chain = "203.0.113.50, 10.0.0.1, 10.0.0.2"
    r1 = client.post("/api/solve", json={"task_id": SEMVER},
                     headers={"X-Forwarded-For": chain})
    r2 = client.post("/api/solve", json={"task_id": SEMVER},
                     headers={"X-Forwarded-For": chain})
    assert r1.status_code == 200 and r2.status_code == 429
    # The bucket key is the left-most client IP, not the proxy hops.
    assert "203.0.113.50" in client.app.state.hits


def test_blocking_solve_runs_off_the_event_loop():
    """#10: the synchronous solve() must be offloaded to a worker thread so a
    single slow solve cannot freeze the asyncio event loop for all callers.

    Discriminator: a function called *directly* inside the async coroutine runs
    on the event-loop thread, where ``asyncio.get_running_loop()`` succeeds. When
    properly offloaded to a threadpool worker there is no running loop in that
    thread, so the call raises ``RuntimeError``. We assert the latter."""
    import asyncio

    captured = {}

    def _record_loop_solve(task, *, run_id, budget_usd, seed):
        try:
            asyncio.get_running_loop()
            captured["on_event_loop"] = True
        except RuntimeError:
            captured["on_event_loop"] = False
        return _fake_solve(task, run_id=run_id, budget_usd=budget_usd, seed=seed)

    app = create_app(solve_fn=_record_loop_solve, tasks={SEMVER: TASKS[SEMVER]})
    client = TestClient(app)
    r = client.post("/api/solve", json={"task_id": SEMVER})
    assert r.status_code == 200
    assert captured["on_event_loop"] is False  # offloaded to a threadpool worker


_TURNSTILE_CALLS: list = []


async def _counting_verify(tok, ip):
    _TURNSTILE_CALLS.append((tok, ip))
    return True


def test_turnstile_runs_after_cheap_local_checks():
    """#40: the cheap local allowlist + rate-limit checks must gate the expensive
    outbound Turnstile siteverify, so unauthenticated/garbage callers cannot
    drive unbounded external verification."""
    _TURNSTILE_CALLS.clear()
    c = _client(require_turnstile=True, turnstile_verify=_counting_verify)
    # Unknown task_id: rejected by the cheap allowlist before Turnstile fires.
    r = c.post("/api/solve", json={"task_id": "garbage", "turnstile_token": "x"})
    assert r.status_code == 400
    assert _TURNSTILE_CALLS == []  # no outbound siteverify for an unknown task


def test_rate_limit_gates_turnstile_calls():
    """#40: once a client is rate-limited, no further Turnstile siteverify
    calls are made for it (the limiter caps outbound verification)."""
    _TURNSTILE_CALLS.clear()
    c = _client(require_turnstile=True, turnstile_verify=_counting_verify, rate_limit=1)
    h = {"X-Forwarded-For": "203.0.113.9"}
    ok = c.post("/api/solve", json={"task_id": SEMVER, "turnstile_token": "x"}, headers=h)
    limited = c.post("/api/solve", json={"task_id": SEMVER, "turnstile_token": "x"}, headers=h)
    assert ok.status_code == 200
    assert limited.status_code == 429
    assert len(_TURNSTILE_CALLS) == 1  # only the request that passed the limiter
