"""Fast, hermetic tests for ``forgejudge.eval.sweep`` main()/CLI + branches.

These cover the argparse entrypoint, seed parsing, the no-store print path, the
store-conn persistence branch, the empty-records resolution_rate, and the
``forced_model_complete`` delegation -- all WITHOUT touching a real LLM
provider, database socket, or the network. The slow/db tests live in
``tests/eval/test_sweep.py`` and are left untouched.
"""

import runpy
import sys
from pathlib import Path

import pytest

import forgejudge.eval.sweep as sweep
from forgejudge.eval.sweep import (
    SweepResult,
    forced_model_complete,
    main,
    run_sweep,
)
from forgejudge.types import GradeResult


class _FakeGrade:
    """Lightweight stand-in for resolution_rate tests (only ``.resolved`` read)."""

    def __init__(self, resolved):
        self.resolved = resolved
        self.judge_score = None


def _real_grade(resolved):
    """A genuine GradeResult so RunRecord(...) validation passes."""
    if resolved:
        return GradeResult(f2p_passed=1, f2p_total=1, p2p_passed=1, p2p_total=1,
                           logs="ok")
    return GradeResult(f2p_passed=0, f2p_total=1, p2p_passed=1, p2p_total=1,
                       logs="fail")


class _FakeSolve:
    patch = "--- a\n+++ b\n"
    tokens_in = 7
    tokens_out = 3
    cost_usd = 0.0
    trace_url = ""
    status = "ok"


def _make_task(instance_id="t1"):
    """A tiny duck-typed Task: run_sweep only reads ``.instance_id``."""

    class _T:
        pass

    t = _T()
    t.instance_id = instance_id
    return t


# --------------------------------------------------------------------------
# SweepResult.resolution_rate (line 32: empty-records branch)
# --------------------------------------------------------------------------


def test_resolution_rate_empty_is_zero():
    assert SweepResult("m", []).resolution_rate == 0.0


def test_resolution_rate_partial():
    recs = [_FakeGrade(True), _FakeGrade(False), _FakeGrade(True), _FakeGrade(False)]
    assert SweepResult("m", recs).resolution_rate == 0.5  # noqa: PLR2004


# --------------------------------------------------------------------------
# forced_model_complete inner fn (lines 38-40: delegates to router.complete)
# --------------------------------------------------------------------------


def test_forced_model_complete_delegates_with_forced_model(monkeypatch):
    captured = {}

    def fake_complete(messages, *, role, run_id, model, seed=None):
        captured.update(messages=messages, role=role, run_id=run_id,
                        model=model, seed=seed)
        return "COMPLETION"

    monkeypatch.setattr(sweep, "complete", fake_complete)

    fn = forced_model_complete("groq/forced-model")
    out = fn([{"role": "user", "content": "hi"}], role="solver",
             run_id="r-1", seed=5)

    assert out == "COMPLETION"
    # The whole point: the forced model id is injected regardless of caller.
    assert captured["model"] == "groq/forced-model"
    assert captured["role"] == "solver"
    assert captured["run_id"] == "r-1"
    assert captured["seed"] == 5


# --------------------------------------------------------------------------
# run_sweep store_conn branch (lines 77-79: insert_run called per record)
# --------------------------------------------------------------------------


def _stub_solve_and_grade(monkeypatch, resolved=True):
    """Replace solve()/grade() in sweep so no LLM/subprocess runs."""
    monkeypatch.setattr(sweep, "solve",
                        lambda task, **kw: _FakeSolve())
    monkeypatch.setattr(sweep, "grade",
                        lambda task, patch, **kw: _real_grade(resolved))


def test_run_sweep_persists_each_record_via_store_conn(monkeypatch):
    _stub_solve_and_grade(monkeypatch, resolved=True)

    inserted = []
    import forgejudge.store.db as db
    monkeypatch.setattr(db, "insert_run",
                        lambda conn, rec: inserted.append((conn, rec)))

    sentinel_conn = object()
    tasks = [_make_task("a"), _make_task("b")]
    res = run_sweep("fake-model", seeds=[0, 1], tasks=tasks,
                    store_conn=sentinel_conn, now="2026-05-29T00:00:00Z")

    # 2 tasks x 2 seeds = 4 records, every one persisted via the store branch.
    assert len(res.records) == 4  # noqa: PLR2004
    assert len(inserted) == 4  # noqa: PLR2004
    assert all(conn is sentinel_conn for conn, _ in inserted)
    assert res.resolution_rate == 1.0
    # run_id is composed from model/task/seed.
    assert res.records[0].run_id == "fake-model-a-seed0"


def test_run_sweep_no_store_does_not_persist(monkeypatch):
    _stub_solve_and_grade(monkeypatch, resolved=False)

    import forgejudge.store.db as db

    def _boom(*a, **k):  # pragma: no cover - must never be called
        raise AssertionError("insert_run must not run without store_conn")

    monkeypatch.setattr(db, "insert_run", _boom)

    res = run_sweep("m", seeds=[3], tasks=[_make_task("x")], store_conn=None,
                    now="2026-05-29T00:00:00Z")
    assert len(res.records) == 1
    assert res.records[0].resolved is False
    assert res.resolution_rate == 0.0


# --------------------------------------------------------------------------
# main() / CLI -- argparse, seed parsing, no-store print, store path, --out
# --------------------------------------------------------------------------


def _patch_main_side_effects(monkeypatch):
    """Neutralise tracing + DB so main() never touches real services."""
    import forgejudge.obs.tracing as tracing
    import forgejudge.store.db as db

    monkeypatch.setattr(tracing, "setup_tracing", lambda: None)
    monkeypatch.setattr(db, "connect", lambda *a, **k: object())
    monkeypatch.setattr(db, "init_db", lambda conn: None)
    monkeypatch.setattr(db, "upsert_tasks", lambda conn, tasks: None)
    monkeypatch.setattr(sweep, "load_tasks", lambda dataset: ["TASK"])


class _RecordingResult:
    """Fake SweepResult returned by the faked run_sweep."""

    def __init__(self, records, rate):
        self.records = records
        self._rate = rate

    @property
    def resolution_rate(self):
        return self._rate


def _fake_run_sweep_factory(calls, *, records=None, rate=0.75):
    recs = records if records is not None else ["r0", "r1"]

    def fake_run_sweep(model, seeds, *, budget_usd, max_steps, store_conn):
        calls.append({"model": model, "seeds": seeds, "budget_usd": budget_usd,
                      "max_steps": max_steps, "store_conn": store_conn})
        return _RecordingResult(recs, rate)

    return fake_run_sweep


def test_main_no_store_parses_seeds_and_prints_rate(monkeypatch, capsys):
    _patch_main_side_effects(monkeypatch)
    calls = []
    monkeypatch.setattr(sweep, "run_sweep",
                        _fake_run_sweep_factory(calls, rate=0.5))
    monkeypatch.setattr("sys.argv",
                        ["sweep", "--model", "groq/llama", "--seeds", "0,2, 5",
                         "--no-store"])

    main()

    assert len(calls) == 1
    c = calls[0]
    # Seeds parsed from comma string, whitespace-tolerant, ints.
    assert c["seeds"] == [0, 2, 5]
    assert c["model"] == "groq/llama"
    # --no-store => no DB connection passed through.
    assert c["store_conn"] is None
    assert c["budget_usd"] == 0.10  # noqa: PLR2004
    assert c["max_steps"] == 6  # noqa: PLR2004

    out = capsys.readouterr().out
    assert "model=groq/llama" in out
    assert "seeds=[0, 2, 5]" in out
    assert "resolution_rate=0.500" in out
    assert "over 2 runs" in out


def test_main_store_path_connects_and_closes(monkeypatch, capsys):
    _patch_main_side_effects(monkeypatch)

    # Track that connect() result is threaded into run_sweep and then closed.
    closed = {"v": False}

    class _Conn:
        def close(self_inner):
            closed["v"] = True

    conn_obj = _Conn()
    import forgejudge.store.db as db
    monkeypatch.setattr(db, "connect", lambda *a, **k: conn_obj)

    upserts = []
    monkeypatch.setattr(db, "upsert_tasks",
                        lambda conn, tasks: upserts.append((conn, tasks)))

    calls = []
    monkeypatch.setattr(sweep, "run_sweep",
                        _fake_run_sweep_factory(calls, rate=1.0))
    monkeypatch.setattr("sys.argv",
                        ["sweep", "--model", "m1", "--seeds", "0",
                         "--budget-usd", "0.5", "--max-steps", "3"])

    main()

    c = calls[0]
    # Default (store) path: the live connection object is handed to run_sweep.
    assert c["store_conn"] is conn_obj
    assert c["budget_usd"] == 0.5  # noqa: PLR2004
    assert c["max_steps"] == 3  # noqa: PLR2004
    # init_db + upsert_tasks ran against the fake loaded tasks.
    assert upserts == [(conn_obj, ["TASK"])]
    # conn.close() called at the end.
    assert closed["v"] is True
    assert "resolution_rate=1.000" in capsys.readouterr().out


def test_main_out_writes_jsonl(monkeypatch, tmp_path, capsys):
    _patch_main_side_effects(monkeypatch)

    class _Rec:
        def __init__(self, i):
            self.i = i

        def model_dump_json(self):
            return f'{{"i": {self.i}}}'

    recs = [_Rec(0), _Rec(1)]
    calls = []
    monkeypatch.setattr(sweep, "run_sweep",
                        _fake_run_sweep_factory(calls, records=recs, rate=0.0))

    out_file = tmp_path / "runs.jsonl"
    monkeypatch.setattr("sys.argv",
                        ["sweep", "--model", "m", "--seeds", "1,1",
                         "--no-store", "--out", str(out_file)])

    main()

    assert out_file.exists()
    lines = out_file.read_text().splitlines()
    assert lines == ['{"i": 0}', '{"i": 1}']
    # Duplicate seeds preserved exactly as parsed.
    assert calls[0]["seeds"] == [1, 1]
    assert "resolution_rate=0.000" in capsys.readouterr().out


def test_main_empty_seeds_string_yields_empty_list(monkeypatch, capsys):
    _patch_main_side_effects(monkeypatch)
    calls = []
    monkeypatch.setattr(sweep, "run_sweep",
                        _fake_run_sweep_factory(calls, records=[], rate=0.0))
    monkeypatch.setattr("sys.argv",
                        ["sweep", "--model", "m", "--seeds", " , ", "--no-store"])

    main()

    assert calls[0]["seeds"] == []
    assert "over 0 runs" in capsys.readouterr().out


def test_main_requires_model(monkeypatch):
    _patch_main_side_effects(monkeypatch)
    monkeypatch.setattr(sweep, "run_sweep",
                        _fake_run_sweep_factory([]))
    monkeypatch.setattr("sys.argv", ["sweep", "--seeds", "0", "--no-store"])

    # argparse should error out (missing required --model) -> SystemExit.
    with pytest.raises(SystemExit):
        main()


# --------------------------------------------------------------------------
# __main__ guard (line 119): run as a script with everything stubbed.
# --------------------------------------------------------------------------


def test_module_run_as_main_invokes_main(monkeypatch, capsys):
    _patch_main_side_effects(monkeypatch)
    # The runpy re-exec imports a fresh module object, so patch the real
    # collaborators on their home modules instead of on `sweep`.
    import forgejudge.llm.router as router
    monkeypatch.setattr(router, "complete",
                        lambda *a, **k: (_ for _ in ()).throw(
                            AssertionError("router.complete must not run")))

    monkeypatch.setattr("sys.argv",
                        ["sweep", "--model", "m", "--seeds", "0", "--no-store"])

    # Stub solve/grade on their source modules too, in case run_sweep runs.
    import forgejudge.agent.solver as solver
    import forgejudge.harness.grade as grade_mod
    monkeypatch.setattr(solver, "solve", lambda task, **kw: _FakeSolve())
    monkeypatch.setattr(grade_mod, "grade",
                        lambda task, patch, **kw: _real_grade(True))
    monkeypatch.setattr("forgejudge.golden.loader.load_tasks",
                        lambda dataset: [])

    # Drop the cached module so runpy re-executes it under __main__ cleanly.
    sys.modules.pop("forgejudge.eval.sweep", None)
    runpy.run_module("forgejudge.eval.sweep", run_name="__main__")

    out = capsys.readouterr().out
    assert "sweep model=m" in out
    assert "over 0 runs" in out


def test_dataset_path_points_at_golden_jsonl():
    # Cheap structural assertion guarding the module constants.
    assert isinstance(sweep.DATASET, Path)
    assert sweep.DATASET.name == "dataset.jsonl"
