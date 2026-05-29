"""Guarded live playground for ForgeJudge (Hugging Face Space, FastAPI).

Defense-in-depth so a public live runner can't be abused or drain free quota:

* **Pre-vetted tasks only** — solve_issue accepts a task_id from a fixed
  allowlist; no free-form prompt ever reaches the model (prompt-injection
  mitigation, OWASP LLM01).
* **Per-IP rate limit** — a sliding window.
* **Fail-closed daily token budget** — once the day's tokens are spent, the
  endpoint returns 503 rather than spending more.
* **Optional Cloudflare Turnstile** — enforced when ``TURNSTILE_SECRET`` is set.

The replay-first playground on the dashboard is the always-on, $0 default; this
live runner is the rate-limited counterpart.
"""

import os
import time
from collections import defaultdict, deque
from datetime import UTC, datetime

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel

from forgejudge.golden.loader import load_tasks
from forgejudge.harness.grade import grade

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATASET = os.path.join(REPO_ROOT, "golden", "dataset.jsonl")

RATE_LIMIT_PER_HOUR = int(os.getenv("RATE_LIMIT_PER_HOUR", "5"))
DAILY_TOKEN_BUDGET = int(os.getenv("DAILY_TOKEN_BUDGET", "200000"))
TURNSTILE_SECRET = os.getenv("TURNSTILE_SECRET", "")
SOLVE_BUDGET_USD = float(os.getenv("SOLVE_BUDGET_USD", "0.05"))


def _load_allowlist() -> dict:
    return {t.instance_id: t for t in load_tasks(DATASET)}


def create_app(*, solve_fn=None, tasks=None, turnstile_verify=None, require_turnstile=None,
               rate_limit=None, daily_budget=None) -> FastAPI:
    app = FastAPI(title="ForgeJudge live playground", docs_url=None, redoc_url=None)
    app.state.tasks = tasks if tasks is not None else _load_allowlist()
    app.state.solve_fn = solve_fn  # lazy default below (avoids importing the LLM stack in tests)
    app.state.turnstile_verify = turnstile_verify or _verify_turnstile
    app.state.require_turnstile = bool(TURNSTILE_SECRET) if require_turnstile is None else require_turnstile
    app.state.rate_limit = RATE_LIMIT_PER_HOUR if rate_limit is None else rate_limit
    app.state.daily_budget = DAILY_TOKEN_BUDGET if daily_budget is None else daily_budget
    app.state.hits: dict[str, deque] = defaultdict(deque)
    app.state.day = datetime.now(UTC).date().isoformat()
    app.state.tokens_today = 0

    def _rate_ok(ip: str) -> bool:
        now = time.time()
        dq = app.state.hits[ip]
        while dq and now - dq[0] > 3600:
            dq.popleft()
        if len(dq) >= app.state.rate_limit:
            return False
        dq.append(now)
        return True

    def _roll_day() -> None:
        today = datetime.now(UTC).date().isoformat()
        if today != app.state.day:
            app.state.day = today
            app.state.tokens_today = 0

    @app.get("/", response_class=HTMLResponse)
    def index():
        ids = sorted(app.state.tasks)
        return (
            "<h1>ForgeJudge — guarded live playground</h1>"
            "<p>Pre-vetted tasks only · per-IP rate limit · fail-closed daily token budget."
            " The always-on replay playground lives at "
            "<a href='https://forgejudge.pages.dev/playground'>forgejudge.pages.dev/playground</a>.</p>"
            f"<p>Runnable task ids ({len(ids)}): {', '.join(ids)}</p>"
        )

    @app.get("/api/tasks")
    def tasks_list():
        return {"tasks": sorted(app.state.tasks)}

    class SolveReq(BaseModel):
        task_id: str
        turnstile_token: str | None = None

    @app.post("/api/solve")
    async def solve_issue(req: SolveReq, request: Request):
        # 1. Turnstile (only when configured).
        if app.state.require_turnstile:
            ok = await app.state.turnstile_verify(req.turnstile_token, request.client.host if request.client else "")
            if not ok:
                return JSONResponse({"error": "turnstile verification failed"}, status_code=403)
        # 2. Pre-vetted task only (no free-form prompt to the model).
        if req.task_id not in app.state.tasks:
            return JSONResponse({"error": "unknown task_id (pre-vetted tasks only)"}, status_code=400)
        # 3. Per-IP rate limit.
        ip = request.client.host if request.client else "?"
        if not _rate_ok(ip):
            return JSONResponse({"error": "rate limit exceeded"}, status_code=429)
        # 4. Fail-closed daily token budget.
        _roll_day()
        if app.state.tokens_today >= app.state.daily_budget:
            return JSONResponse({"error": "daily token budget exhausted; try the replay playground"},
                                status_code=503)

        task = app.state.tasks[req.task_id]
        solve_fn = app.state.solve_fn
        if solve_fn is None:
            from forgejudge.agent.solver import solve as solve_fn
        res = solve_fn(task, run_id=f"hf-{req.task_id}", budget_usd=SOLVE_BUDGET_USD, seed=0)
        app.state.tokens_today += (res.tokens_in + res.tokens_out)
        g = grade(task, res.patch)
        return {
            "task_id": req.task_id, "resolved": g.resolved,
            "f2p": f"{g.f2p_passed}/{g.f2p_total}", "p2p": f"{g.p2p_passed}/{g.p2p_total}",
            "patch": res.patch, "trace_url": res.trace_url, "status": res.status,
        }

    return app


async def _verify_turnstile(token: str | None, ip: str) -> bool:
    if not token:
        return False
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.post(
            "https://challenges.cloudflare.com/turnstile/v0/siteverify",
            data={"secret": TURNSTILE_SECRET, "response": token, "remoteip": ip},
        )
        return bool(r.json().get("success"))


app = create_app()
