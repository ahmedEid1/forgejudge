"""Hermetic tests for the dashboard JSON snapshot exporter.

``forgejudge.store.export`` reads the run store (a Postgres connection + the
``leaderboard`` aggregation) and writes ``dashboard/public/data/{leaderboard,
runs}.json`` for the static dashboard. These tests run WITHOUT a real database:
``connect`` and ``leaderboard`` are monkeypatched and a tiny fake connection
returns canned rows, so we assert the exact JSON shape ``dashboard/public/
app.js`` consumes (keys, types, ordering) plus the empty / cleanup branches.
"""

import json
import runpy

import pytest

import forgejudge.store.export as export
from forgejudge.store.export import export_snapshot, main

# Column order MUST match _RUNS_SQL's SELECT list in export.py, since the
# exporter zips raw tuples against _RUN_COLS by position.
_RUN_TUPLE = (
    "run-1",          # run_id
    "task-a",         # task_id
    "gpt-x",          # model
    "0.1.0",          # scaffold_version
    0,                # seed
    True,             # resolved
    1,                # f2p_passed
    1,                # f2p_total
    2,                # p2p_passed
    2,                # p2p_total
    100,              # tokens_in
    50,               # tokens_out
    0.0123,           # cost_usd
    1.5,              # wall_clock_s
    "https://lf/r1",  # trace_url
    0.9,              # judge_score
    "ok",             # status
    "2026-05-29T00:00:00Z",  # created_at
    "fix the bug",    # problem_statement (COALESCE'd in SQL)
    "--- a\n+++ b\n",  # patch
)

_BOARD = [
    {"model": "gpt-x", "scaffold_version": "0.1.0", "n_tasks": 3, "n_runs": 9,
     "n_seeds": 3, "pass_at_1": 0.66, "pass_at_k": 0.9, "mean_cost_usd": 0.04,
     "mean_tokens": 450.0, "mean_wall_s": 1.5},
    {"model": "claude-y", "scaffold_version": "0.1.0", "n_tasks": 3, "n_runs": 9,
     "n_seeds": 3, "pass_at_1": 0.33, "pass_at_k": 0.6, "mean_cost_usd": 0.02,
     "mean_tokens": 300.0, "mean_wall_s": 2.0},
]


class _FakeCursor:
    def __init__(self, *, one=None, all_=None):
        self._one = one
        self._all = all_

    def fetchone(self):
        return self._one

    def fetchall(self):
        return self._all


class _FakeConn:
    """Stands in for a psycopg connection. ``execute`` dispatches on the SQL:
    the ``count(*)`` query returns ``n_tasks``; everything else returns runs."""

    def __init__(self, *, n_tasks, run_rows):
        self._n_tasks = n_tasks
        self._run_rows = run_rows
        self.closed = False
        self.executed = []

    def execute(self, sql, *args, **kwargs):
        self.executed.append(sql)
        if "count(*)" in sql.lower():
            return _FakeCursor(one=(self._n_tasks,))
        return _FakeCursor(all_=self._run_rows)

    def close(self):
        self.closed = True


@pytest.fixture
def patched(monkeypatch):
    """Patch connect/leaderboard on the export module; yield a controllable
    fake conn the test can inspect (e.g. for ``.closed``)."""
    holder = {}

    def _install(*, n_tasks=3, run_rows=(_RUN_TUPLE,), board=None):
        conn = _FakeConn(n_tasks=n_tasks, run_rows=list(run_rows))
        holder["conn"] = conn
        monkeypatch.setattr(export, "connect", lambda *a, **k: conn)
        monkeypatch.setattr(
            export, "leaderboard",
            lambda c: list(_BOARD if board is None else board),
        )
        return conn

    holder["install"] = _install
    return holder


def _read(out_dir):
    lb = json.loads((out_dir / "leaderboard.json").read_text())
    runs = json.loads((out_dir / "runs.json").read_text())
    return lb, runs


def test_writes_both_json_files(patched, tmp_path):
    patched["install"]()
    export_snapshot(tmp_path, now="2026-05-29T12:00:00+00:00")
    assert (tmp_path / "leaderboard.json").is_file()
    assert (tmp_path / "runs.json").is_file()


def test_leaderboard_json_shape_and_keys(patched, tmp_path):
    patched["install"]()
    export_snapshot(tmp_path, now="2026-05-29T12:00:00+00:00")
    lb, _ = _read(tmp_path)
    assert set(lb.keys()) == {"generated_at", "n_tasks", "models"}
    assert lb["generated_at"] == "2026-05-29T12:00:00+00:00"
    assert lb["n_tasks"] == 3
    # app.js reads m.model, m.pass_at_1, m.pass_at_k, m.mean_cost_usd,
    # m.mean_tokens, m.mean_wall_s, m.n_runs, m.n_seeds, m.scaffold_version.
    m0 = lb["models"][0]
    for key in ("model", "scaffold_version", "n_runs", "n_seeds", "pass_at_1",
                "pass_at_k", "mean_cost_usd", "mean_tokens", "mean_wall_s"):
        assert key in m0


def test_leaderboard_models_preserve_query_ordering(patched, tmp_path):
    patched["install"]()
    export_snapshot(tmp_path, now="2026-05-29T12:00:00+00:00")
    lb, _ = _read(tmp_path)
    # The exporter must NOT reorder; it emits leaderboard() rows verbatim
    # (db.py already ORDERs by pass_at_1 DESC). gpt-x (0.66) before claude-y.
    assert [m["model"] for m in lb["models"]] == ["gpt-x", "claude-y"]


def test_runs_json_shape_and_column_mapping(patched, tmp_path):
    patched["install"]()
    export_snapshot(tmp_path, now="2026-05-29T12:00:00+00:00")
    _, runs = _read(tmp_path)
    assert set(runs.keys()) == {"generated_at", "runs"}
    assert len(runs["runs"]) == 1
    r = runs["runs"][0]
    # Raw tuple zipped against _RUN_COLS — verify the positional mapping is
    # correct for the fields app.js renders.
    assert r["run_id"] == "run-1"
    assert r["task_id"] == "task-a"
    assert r["model"] == "gpt-x"
    assert r["resolved"] is True
    assert r["f2p_passed"] == 1 and r["f2p_total"] == 1
    assert r["p2p_passed"] == 2 and r["p2p_total"] == 2
    assert r["tokens_in"] == 100 and r["tokens_out"] == 50
    assert r["wall_clock_s"] == 1.5
    assert r["trace_url"] == "https://lf/r1"
    assert r["problem_statement"] == "fix the bug"
    assert r["patch"] == "--- a\n+++ b\n"
    # Every declared column is present.
    assert set(r.keys()) == set(export._RUN_COLS)


def test_summary_return_value(patched, tmp_path):
    patched["install"]()
    summary = export_snapshot(tmp_path, now="2026-05-29T12:00:00+00:00")
    assert summary == {"models": 2, "runs": 1, "n_tasks": 3, "out": str(tmp_path)}


def test_creates_nested_output_directory(patched, tmp_path):
    patched["install"]()
    nested = tmp_path / "deep" / "data"
    assert not nested.exists()
    export_snapshot(nested, now="2026-05-29T12:00:00+00:00")
    assert (nested / "leaderboard.json").is_file()


def test_accepts_str_path(patched, tmp_path):
    patched["install"]()
    summary = export_snapshot(str(tmp_path), now="2026-05-29T12:00:00+00:00")
    assert summary["out"] == str(tmp_path)


def test_connection_closed_even_on_query_error(patched, tmp_path, monkeypatch):
    """The ``finally: conn.close()`` must run if a query raises mid-export."""
    conn = patched["install"]()

    def _boom(c):
        raise RuntimeError("db exploded")

    monkeypatch.setattr(export, "leaderboard", _boom)
    with pytest.raises(RuntimeError, match="db exploded"):
        export_snapshot(tmp_path)
    assert conn.closed is True
    # Nothing should have been written before the failure.
    assert not (tmp_path / "leaderboard.json").exists()


def test_connection_closed_on_success(patched, tmp_path):
    conn = patched["install"]()
    export_snapshot(tmp_path, now="2026-05-29T12:00:00+00:00")
    assert conn.closed is True


def test_empty_results(patched, tmp_path):
    """Empty board + zero runs + zero tasks: valid empty snapshot, no crash."""
    patched["install"](n_tasks=0, run_rows=(), board=[])
    summary = export_snapshot(tmp_path, now="2026-05-29T12:00:00+00:00")
    assert summary == {"models": 0, "runs": 0, "n_tasks": 0, "out": str(tmp_path)}
    lb, runs = _read(tmp_path)
    assert lb["models"] == []
    assert lb["n_tasks"] == 0
    assert runs["runs"] == []


def test_default_now_is_iso_utc(patched, tmp_path):
    """Without an explicit ``now``, generated_at is an ISO-8601 UTC string that
    app.js can parse and slice (it does Date(...) then .slice(0,16))."""
    patched["install"]()
    before = export.datetime.now(export.UTC)
    export_snapshot(tmp_path)
    lb, runs = _read(tmp_path)
    gen = lb["generated_at"]
    # Same value written to both files.
    assert runs["generated_at"] == gen
    parsed = export.datetime.fromisoformat(gen)
    assert parsed.tzinfo is not None  # tz-aware
    assert parsed >= before.replace(microsecond=0) or parsed >= before


def test_json_is_indented(patched, tmp_path):
    """Files are written with indent=2 (human-diffable snapshots)."""
    patched["install"]()
    export_snapshot(tmp_path, now="2026-05-29T12:00:00+00:00")
    text = (tmp_path / "leaderboard.json").read_text()
    assert "\n  " in text  # 2-space indentation present


def test_main_prints_summary(patched, tmp_path, monkeypatch, capsys):
    patched["install"]()
    monkeypatch.setattr("sys.argv", ["export", "--out", str(tmp_path)])
    main()
    out = capsys.readouterr().out
    assert "exported 2 model(s), 1 run(s)" in out
    assert str(tmp_path) in out
    assert (tmp_path / "leaderboard.json").is_file()


def test_main_default_out(patched, monkeypatch):
    """With no --out, main() falls back to DEFAULT_OUT (argparse default)."""
    captured = {}

    def _fake_export(out, **kwargs):
        captured["out"] = out
        return {"models": 0, "runs": 0, "n_tasks": 0, "out": out}

    monkeypatch.setattr(export, "export_snapshot", _fake_export)
    monkeypatch.setattr("sys.argv", ["export"])
    main()
    assert captured["out"] == str(export.DEFAULT_OUT)


def test_module_run_as_script(patched, tmp_path, monkeypatch):
    """Cover the ``if __name__ == '__main__': main()`` guard by executing the
    source file via runpy (still hermetic: the db functions it imports are
    patched, so no real connection is made)."""
    conn = _FakeConn(n_tasks=0, run_rows=[])
    monkeypatch.setattr("forgejudge.store.db.connect", lambda *a, **k: conn)
    monkeypatch.setattr("forgejudge.store.db.leaderboard", lambda c: [])
    monkeypatch.setattr("sys.argv", ["export", "--out", str(tmp_path)])
    runpy.run_path(export.__file__, run_name="__main__")
    assert (tmp_path / "leaderboard.json").is_file()
