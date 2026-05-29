"""The FastMCP server exposes solve_issue / get_run / get_leaderboard and the
tool logic behaves. Requires the optional 'mcp' extra (fastmcp)."""

import json
from pathlib import Path

import anyio
import pytest

pytest.importorskip("fastmcp")

from fastmcp import Client  # noqa: E402

from forgejudge.agent.solver import SolveResult  # noqa: E402
from forgejudge.mcp.server import _solve_issue_impl, mcp  # noqa: E402

pytestmark = pytest.mark.mcp

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SEMVER = "fixture-semver-001"


def test_tools_are_registered_with_valid_schemas():
    async def go():
        async with Client(mcp) as client:
            tools = await client.list_tools()
            names = {t.name for t in tools}
            assert {"solve_issue", "get_run", "get_leaderboard"} <= names
            # every tool has an input schema
            for t in tools:
                assert t.inputSchema is not None
    anyio.run(go)


def test_server_json_manifest_is_valid():
    manifest = json.loads((REPO_ROOT / "forgejudge" / "mcp" / "server.json").read_text())
    assert manifest["name"].startswith("io.github.")
    assert manifest["version"]
    assert manifest["repository"]["url"].endswith("/forgejudge")


def test_solve_issue_impl_grades_a_gold_patch():
    gold = json.loads(
        next(line for line in (REPO_ROOT / "golden" / "solutions.jsonl").read_text().splitlines()
             if SEMVER in line)
    )["gold_patch"]

    def fake_solve(task, *, run_id, budget_usd, seed):
        return SolveResult(patch=gold, status="ok", steps=1, cost_usd=0.0,
                           resolved_in_loop=False, trace_url="https://lf/x")

    out = _solve_issue_impl(SEMVER, solve_fn=fake_solve)
    assert out["task_id"] == SEMVER
    assert out["resolved"] is True
    assert out["trace_url"] == "https://lf/x"
    assert out["f2p"].split("/")[0] == out["f2p"].split("/")[1]  # all f2p passed


def test_solve_issue_impl_rejects_unknown_task():
    with pytest.raises(ValueError, match="unknown task_id"):
        _solve_issue_impl("does-not-exist", solve_fn=lambda *a, **k: None)
