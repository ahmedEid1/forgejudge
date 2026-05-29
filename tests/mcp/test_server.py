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


def _pyproject_version() -> str:
    import tomllib

    data = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text())
    return data["project"]["version"]


def test_server_json_manifest_is_valid():
    manifest = json.loads((REPO_ROOT / "forgejudge" / "mcp" / "server.json").read_text())
    assert manifest["name"].startswith("io.github.")
    assert manifest["version"]
    assert manifest["repository"]["url"].endswith("/forgejudge")


def test_manifest_package_is_internally_consistent():
    """#24: the packages[] block must be usable — its version must match the
    published package (pyproject), and its declared transport must match the
    only runnable entrypoint (server.py main())."""
    import inspect

    from forgejudge.mcp import server as srv

    manifest = json.loads((REPO_ROOT / "forgejudge" / "mcp" / "server.json").read_text())
    pkgs = manifest["packages"]
    assert pkgs, "manifest must declare at least one package"
    pkg = pkgs[0]

    # (3) version must match the real package version, not a stale 0.0.1.
    pyver = _pyproject_version()
    assert pkg["version"] == pyver == manifest["version"], (
        f"package version {pkg['version']!r} != pyproject {pyver!r}"
    )

    # (2) declared transport must match what main() actually runs.
    declared = pkg["transport"]["type"]
    main_src = inspect.getsource(srv.main)
    assert f'transport="{declared}"' in main_src, (
        f"manifest declares transport {declared!r} but main() does not run it"
    )

    # (1) a stdio package with no console-script must declare a concrete way to
    # launch it (runtimeHint + arguments), otherwise a client has nothing to exec.
    if declared == "stdio":
        assert pkg.get("runtimeHint"), "stdio package needs a runtimeHint to launch"
        args = pkg.get("runtimeArguments") or pkg.get("packageArguments")
        assert args, "stdio package needs run arguments (no console-script exists)"


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


# --------------------------------------------------------------------------- #
# Appended coverage tests (handlers + error/not-found paths). All hermetic:    #
# db.connect / db.leaderboard / db.get_run are monkeypatched so no real DB     #
# socket is opened, and the solver is faked so no LLM/provider call is made.   #
# --------------------------------------------------------------------------- #

from forgejudge.types import GradeResult, RunRecord  # noqa: E402


class _FakeConn:
    """Stand-in psycopg connection that records whether close() ran."""

    def __init__(self) -> None:
        self.closed = False

    def close(self) -> None:
        self.closed = True


def _make_run_record() -> RunRecord:
    return RunRecord(
        run_id="run-42",
        task_id=SEMVER,
        model="claude-x",
        scaffold_version="v1",
        seed=0,
        resolved=True,
        grade=GradeResult(f2p_passed=2, f2p_total=2, p2p_passed=3, p2p_total=3, logs="ok"),
        patch="diff --git a b",
        tokens_in=10,
        tokens_out=20,
        cost_usd=0.01,
        wall_clock_s=1.5,
        trace_url="https://lf/run-42",
        judge_score=None,
        status="ok",
        created_at="2026-01-01",
    )


def test_leaderboard_impl_passes_through_rows_and_closes_conn(monkeypatch):
    from forgejudge.mcp import server as srv

    fake = _FakeConn()
    rows = [{"model": "claude-x", "pass_at_1": 0.5}]
    monkeypatch.setattr(srv.db, "connect", lambda: fake)
    monkeypatch.setattr(srv.db, "leaderboard", lambda conn: rows)

    out = srv._leaderboard_impl()

    assert out is rows
    assert fake.closed is True  # finally: conn.close() ran


def test_leaderboard_impl_closes_conn_even_when_query_raises(monkeypatch):
    from forgejudge.mcp import server as srv

    fake = _FakeConn()

    def boom(conn):
        raise RuntimeError("query failed")

    monkeypatch.setattr(srv.db, "connect", lambda: fake)
    monkeypatch.setattr(srv.db, "leaderboard", boom)

    with pytest.raises(RuntimeError, match="query failed"):
        srv._leaderboard_impl()
    assert fake.closed is True  # finally still ran on the error path


def test_get_run_impl_returns_dumped_record(monkeypatch):
    from forgejudge.mcp import server as srv

    fake = _FakeConn()
    rec = _make_run_record()
    monkeypatch.setattr(srv.db, "connect", lambda: fake)
    monkeypatch.setattr(srv.db, "get_run", lambda conn, run_id: rec)

    out = srv._get_run_impl("run-42")

    assert isinstance(out, dict)
    assert out["run_id"] == "run-42"
    assert out["trace_url"] == "https://lf/run-42"
    assert out == rec.model_dump()
    assert fake.closed is True


def test_get_run_impl_returns_none_when_not_found(monkeypatch):
    from forgejudge.mcp import server as srv

    fake = _FakeConn()
    monkeypatch.setattr(srv.db, "connect", lambda: fake)
    monkeypatch.setattr(srv.db, "get_run", lambda conn, run_id: None)

    out = srv._get_run_impl("missing")

    assert out is None  # not-found branch
    assert fake.closed is True


def test_get_leaderboard_tool_wrapper_delegates_to_impl(monkeypatch):
    from forgejudge.mcp import server as srv

    sentinel = [{"model": "m"}]
    monkeypatch.setattr(srv, "_leaderboard_impl", lambda: sentinel)
    assert srv.get_leaderboard() is sentinel


def test_get_run_tool_wrapper_delegates_to_impl(monkeypatch):
    from forgejudge.mcp import server as srv

    captured = {}

    def fake_impl(run_id):
        captured["run_id"] = run_id
        return {"run_id": run_id}

    monkeypatch.setattr(srv, "_get_run_impl", fake_impl)
    out = srv.get_run("run-99")
    assert out == {"run_id": "run-99"}
    assert captured["run_id"] == "run-99"


def test_solve_issue_tool_wrapper_forwards_args_to_impl(monkeypatch):
    from forgejudge.mcp import server as srv

    captured = {}

    def fake_impl(task_id, *, budget_usd, seed):
        captured.update(task_id=task_id, budget_usd=budget_usd, seed=seed)
        return {"task_id": task_id}

    monkeypatch.setattr(srv, "_solve_issue_impl", fake_impl)
    out = srv.solve_issue("t1", budget_usd=0.25, seed=7)
    assert out == {"task_id": "t1"}
    assert captured == {"task_id": "t1", "budget_usd": 0.25, "seed": 7}


def test_solve_issue_impl_lazy_imports_default_solver(monkeypatch):
    """With solve_fn=None the impl must lazily import the real solver symbol
    (server.py:53). We replace solver.solve with a fake so no LLM is called."""
    import forgejudge.agent.solver as solver_mod

    def fake_solve(task, *, run_id, budget_usd, seed):
        assert run_id == f"mcp-{SEMVER}-seed0"
        return SolveResult(
            patch="", status="error", steps=0, cost_usd=0.0,
            resolved_in_loop=False, trace_url="https://lf/lazy",
        )

    monkeypatch.setattr(solver_mod, "solve", fake_solve)

    out = _solve_issue_impl(SEMVER)  # solve_fn defaults to None -> lazy import path

    assert out["task_id"] == SEMVER
    assert out["status"] == "error"
    assert out["trace_url"] == "https://lf/lazy"
    assert out["resolved"] is False  # empty patch grades as not resolved


def test_main_runs_stdio_transport(monkeypatch):
    from forgejudge.mcp import server as srv

    calls = {}
    monkeypatch.setattr(srv.mcp, "run", lambda *, transport: calls.setdefault("transport", transport))
    srv.main()
    assert calls["transport"] == "stdio"  # matches the manifest's declared transport
