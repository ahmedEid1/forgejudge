"""Quality-gated publish: a degraded (rate-limited) sweep must never overwrite
good leaderboard data. Hermetic — no DB, no network."""

import forgejudge.eval.publish as P
from forgejudge.eval.publish import error_rate, gate, load_runs, model_of, publish
from forgejudge.types import GradeResult, RunRecord


def _run(model: str, status: str, *, resolved: bool = True, seed: int = 0) -> RunRecord:
    g = GradeResult(
        f2p_passed=2 if resolved else 0, f2p_total=2,
        p2p_passed=3, p2p_total=3, logs="",
    )
    return RunRecord(
        run_id=f"{model}-t-{seed}", task_id="t", model=model, scaffold_version="0.1.0",
        seed=seed, resolved=g.resolved, grade=g, patch="", tokens_in=1, tokens_out=1,
        cost_usd=0.0, wall_clock_s=0.1, trace_url="", status=status, created_at="2026-05-30",
    )


def test_error_rate():
    assert error_rate([]) == 0.0
    recs = [_run("m", "ok") for _ in range(3)] + [_run("m", "error") for _ in range(1)]
    assert error_rate(recs) == 0.25


def test_gate_rejects_degraded():
    recs = [_run("m", "error", resolved=False) for _ in range(50)] + [_run("m", "ok") for _ in range(4)]
    ok, reason = gate(recs, max_error_rate=0.25)
    assert ok is False and "degraded" in reason


def test_gate_flags_all_errored_as_a_hard_failure_not_a_rate_limit():
    # e.g. a model the provider retired: every call fails with model_not_found
    recs = [_run("m", "error", resolved=False) for _ in range(54)]
    ok, reason = gate(recs, max_error_rate=0.25)
    assert ok is False and "degraded" in reason
    assert "every run errored" in reason and "rate-limited" not in reason


def test_gate_accepts_healthy():
    recs = [_run("m", "ok") for _ in range(17)] + [_run("m", "error", resolved=False)]
    ok, reason = gate(recs, max_error_rate=0.25)
    assert ok is True and "ok" in reason


def test_gate_rejects_empty():
    ok, reason = gate([], max_error_rate=0.25)
    assert ok is False and reason == "empty"


def test_model_of():
    recs = [_run("groq/big", "ok"), _run("groq/big", "ok"), _run("groq/small", "ok")]
    assert model_of(recs) == "groq/big"
    assert model_of([]) == "unknown"


def test_load_runs_roundtrip(tmp_path):
    recs = [_run("m", "ok", seed=0), _run("m", "error", resolved=False, seed=1)]
    f = tmp_path / "runs-m.jsonl"
    f.write_text("\n".join(r.model_dump_json() for r in recs) + "\n")
    loaded = load_runs(f)
    assert [r.run_id for r in loaded] == [r.run_id for r in recs]
    assert [r.status for r in loaded] == ["ok", "error"]


def test_publish_inserts_healthy_skips_degraded(tmp_path, monkeypatch):
    good = tmp_path / "runs-good.jsonl"
    bad = tmp_path / "runs-bad.jsonl"
    good_recs = [_run("groq/good", "ok", seed=i) for i in range(18)]
    bad_recs = [_run("groq/bad", "error", resolved=False, seed=i) for i in range(17)] + [_run("groq/bad", "ok")]
    good.write_text("\n".join(r.model_dump_json() for r in good_recs) + "\n")
    bad.write_text("\n".join(r.model_dump_json() for r in bad_recs) + "\n")

    inserted: list[RunRecord] = []
    import forgejudge.store.db as db
    monkeypatch.setattr(db, "insert_runs", lambda conn, runs: inserted.extend(runs))
    monkeypatch.setattr(P, "export_snapshot", lambda out_dir=None, *, now=None: {
        "models": 1, "runs": len(inserted), "n_tasks": 18, "out": str(out_dir)})

    report = publish([good, bad], conn=object(), out_dir=tmp_path, max_error_rate=0.25)

    # only the healthy model's runs were inserted
    assert {r.model for r in inserted} == {"groq/good"}
    assert len(inserted) == 18
    assert [e["model"] for e in report["published"]] == ["groq/good"]
    assert [e["model"] for e in report["skipped"]] == ["groq/bad"]
    assert report["exported"] is True


def test_publish_exports_even_when_all_skipped(tmp_path, monkeypatch):
    bad = tmp_path / "runs-bad.jsonl"
    bad.write_text("\n".join(_run("groq/bad", "error", resolved=False).model_dump_json() for _ in range(10)) + "\n")
    import forgejudge.store.db as db
    monkeypatch.setattr(db, "insert_runs", lambda conn, runs: (_ for _ in ()).throw(AssertionError("must not insert")))
    monkeypatch.setattr(P, "export_snapshot", lambda out_dir=None, *, now=None: {"models": 0, "runs": 0, "n_tasks": 18, "out": str(out_dir)})
    report = publish([bad], conn=object(), out_dir=tmp_path, max_error_rate=0.25)
    assert report["published"] == []
    assert report["skipped"][0]["model"] == "groq/bad"
    assert report["exported"] is True  # skipped models keep prior Neon data; snapshot still refreshes


def test_main_seeds_the_tasks_table_before_publishing(tmp_path, monkeypatch):
    # The sweep runs with --no-store, so on a fresh database publish is the only
    # step that can fill `tasks`; without it the export reports 0 tasks.
    import forgejudge.store.db as db

    runs = tmp_path / "runs-m.jsonl"
    runs.write_text(_run("m", "ok").model_dump_json() + "\n")
    calls = []
    monkeypatch.setattr(db, "connect", lambda *a, **k: type("C", (), {"close": lambda self: None})())
    monkeypatch.setattr(db, "init_db", lambda conn: calls.append("init_db"))
    monkeypatch.setattr(db, "upsert_tasks", lambda conn, tasks: calls.append(("upsert_tasks", len(tasks))))

    def fake_publish(files, **kw):
        calls.append("publish")
        return {"published": [{"model": "m", "n": 1, "reason": "ok"}], "skipped": [], "exported": False}

    monkeypatch.setattr(P, "publish", fake_publish)
    monkeypatch.setattr("sys.argv", ["publish", "--runs", str(tmp_path / "runs-*.jsonl"), "--no-export"])

    P.main()

    assert calls == ["init_db", ("upsert_tasks", 18), "publish"]
