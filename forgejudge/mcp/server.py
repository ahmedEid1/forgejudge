"""ForgeJudge MCP server (FastMCP, stdio).

Launched locally over stdio (``python -m forgejudge.mcp.server``); this is the
transport the published ``server.json`` manifest advertises so an MCP client can
spawn the server directly from the pypi package.

Exposes the agent + leaderboard over the Model Context Protocol:

* ``get_leaderboard()`` — current per-model pass@1/pass@3 + cost/tokens/latency
* ``get_run(run_id)``   — one RunRecord (score, patch, trace URL, ...)
* ``solve_issue(task_id)`` — run the agent on a golden task and grade the patch

Tool logic lives in plain ``_impl`` functions so it is unit-testable without the
MCP transport; the ``@mcp.tool`` wrappers are thin.
"""

from pathlib import Path

from fastmcp import FastMCP

from forgejudge.golden.loader import load_tasks
from forgejudge.store import db

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DATASET = REPO_ROOT / "golden" / "dataset.jsonl"

mcp = FastMCP("forgejudge")


def _leaderboard_impl() -> list[dict]:
    conn = db.connect()
    try:
        return db.leaderboard(conn)
    finally:
        conn.close()


def _get_run_impl(run_id: str) -> dict | None:
    conn = db.connect()
    try:
        rec = db.get_run(conn, run_id)
        return rec.model_dump() if rec else None
    finally:
        conn.close()


def _solve_issue_impl(task_id: str, *, budget_usd: float = 0.10, seed: int = 0, solve_fn=None) -> dict:
    tasks = {t.instance_id: t for t in load_tasks(DATASET)}
    if task_id not in tasks:
        raise ValueError(f"unknown task_id {task_id!r}")
    task = tasks[task_id]
    if solve_fn is None:
        from forgejudge.agent.solver import solve as solve_fn  # lazy: avoids LLM import in tests
    from forgejudge.harness.grade import grade

    res = solve_fn(task, run_id=f"mcp-{task_id}-seed{seed}", budget_usd=budget_usd, seed=seed)
    g = grade(task, res.patch)
    return {
        "task_id": task_id,
        "resolved": g.resolved,
        "f2p": f"{g.f2p_passed}/{g.f2p_total}",
        "p2p": f"{g.p2p_passed}/{g.p2p_total}",
        "patch": res.patch,
        "status": res.status,
        "trace_url": res.trace_url,
        "tokens_in": res.tokens_in,
        "tokens_out": res.tokens_out,
        "cost_usd": res.cost_usd,
    }


@mcp.tool
def get_leaderboard() -> list[dict]:
    """Return the current ForgeJudge leaderboard (one row per model)."""
    return _leaderboard_impl()


@mcp.tool
def get_run(run_id: str) -> dict | None:
    """Return a single run record (score, patch, Langfuse trace URL) by id."""
    return _get_run_impl(run_id)


@mcp.tool
def solve_issue(task_id: str, budget_usd: float = 0.10, seed: int = 0) -> dict:
    """Run the ForgeJudge agent on a golden task and grade its patch."""
    return _solve_issue_impl(task_id, budget_usd=budget_usd, seed=seed)


def main() -> None:
    # stdio: an MCP client launches this module as a subprocess and speaks the
    # protocol over stdin/stdout. Matches the transport declared in server.json.
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
