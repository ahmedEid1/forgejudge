"""The sandbox grade executor: gold patches resolve every task, empty patches
resolve none, sharding partitions the set, and aggregation concatenates."""

import json
from pathlib import Path

import pytest

import forgejudge.harness.runner_actions as ra
from forgejudge.golden.build_dataset import load_solutions
from forgejudge.golden.loader import load_tasks
from forgejudge.harness.runner_actions import aggregate, grade_tasks, main, select_shard
from forgejudge.types import GradeResult, RunRecord

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
TASKS = load_tasks(REPO_ROOT / "golden" / "dataset.jsonl")
GOLD = load_solutions(REPO_ROOT / "golden" / "solutions.jsonl")


def test_select_shard_partitions_all_tasks():
    n = 4
    shards = [select_shard(TASKS, s, n) for s in range(n)]
    flat = [t.instance_id for sh in shards for t in sh]
    assert sorted(flat) == sorted(t.instance_id for t in TASKS)  # exact partition, no overlap


@pytest.mark.slow
def test_gold_patches_resolve_every_task():
    records = grade_tasks(TASKS, GOLD, model="gold", seed=0, now="2026-05-29T00:00:00Z")
    assert len(records) == len(TASKS)
    unresolved = [r.task_id for r in records if not r.resolved]
    assert not unresolved, f"gold patches must resolve every task; failed: {unresolved}"
    r0 = records[0]
    assert r0.scaffold_version and r0.status == "ok" and r0.run_id


@pytest.mark.slow
def test_empty_patches_resolve_nothing():
    records = grade_tasks(TASKS, {}, model="empty", seed=0, now="2026-05-29T00:00:00Z")
    assert all(not r.resolved for r in records)


def test_aggregate_concatenates(tmp_path):
    (tmp_path / "a.jsonl").write_text('{"resolved": true}\n{"resolved": false}\n')
    (tmp_path / "b.jsonl").write_text('{"resolved": true}\n')
    resolved, total = aggregate(tmp_path, tmp_path / "all.jsonl")
    assert (resolved, total) == (2, 3)
    assert len((tmp_path / "all.jsonl").read_text().splitlines()) == 3


# --- Finding #36: the gold self-test must FAIL (non-zero exit) when any gold
# task is unresolved; aggregate of a gold run must fail when resolved != total. ---

def _fake_record(task_id: str, *, resolved: bool, model: str = "gold") -> RunRecord:
    g = GradeResult(
        f2p_passed=1 if resolved else 0, f2p_total=1, p2p_passed=1, p2p_total=1, logs=""
    )
    return RunRecord(
        run_id=f"{model}-{task_id}-seed0", task_id=task_id, model=model,
        scaffold_version="0", seed=0, resolved=resolved, grade=g, patch="",
        tokens_in=0, tokens_out=0, cost_usd=0.0, wall_clock_s=0.0, trace_url="",
        status="ok", created_at="2026-05-29T00:00:00Z",
    )


def _stub_grade(monkeypatch, records):
    """Make main() produce ``records`` without running the real harness."""
    monkeypatch.setattr(ra, "load_tasks", lambda _p: [type("T", (), {"instance_id": r.task_id})() for r in records])
    monkeypatch.setattr(ra, "select_shard", lambda tasks, s, n: tasks)
    monkeypatch.setattr(ra, "load_solutions", lambda: {})
    monkeypatch.setattr(ra, "grade_tasks", lambda *a, **k: records)


def test_gold_self_test_exits_nonzero_when_any_unresolved(tmp_path, monkeypatch):
    records = [_fake_record("t1", resolved=True), _fake_record("t2", resolved=False)]
    _stub_grade(monkeypatch, records)
    out = tmp_path / "runs.jsonl"
    monkeypatch.setattr("sys.argv", [
        "runner_actions", "--patch-source", "gold", "--model", "gold", "--out", str(out),
    ])
    with pytest.raises(SystemExit) as exc:
        main()
    assert exc.value.code != 0  # an unresolved gold task must fail the self-test


def test_gold_self_test_exits_zero_when_all_resolved(tmp_path, monkeypatch):
    records = [_fake_record("t1", resolved=True), _fake_record("t2", resolved=True)]
    _stub_grade(monkeypatch, records)
    out = tmp_path / "runs.jsonl"
    monkeypatch.setattr("sys.argv", [
        "runner_actions", "--patch-source", "gold", "--model", "gold", "--out", str(out),
    ])
    main()  # all resolved -> no exception, exit 0


def test_empty_source_does_not_fail_on_unresolved(tmp_path, monkeypatch):
    # --patch-source empty is the "must resolve nothing" baseline; unresolved is
    # the expected (correct) outcome and must NOT fail the process.
    records = [_fake_record("t1", resolved=False, model="empty")]
    _stub_grade(monkeypatch, records)
    out = tmp_path / "runs.jsonl"
    monkeypatch.setattr("sys.argv", [
        "runner_actions", "--patch-source", "empty", "--model", "empty", "--out", str(out),
    ])
    main()  # no exception


def test_aggregate_gold_run_exits_nonzero_when_unresolved(tmp_path, monkeypatch):
    # The standalone eval.yml aggregate step must fail when a gold run has an
    # unresolved task (resolved != total).
    (tmp_path / "a.jsonl").write_text(
        json.dumps({"model": "gold", "resolved": True}) + "\n"
        + json.dumps({"model": "gold", "resolved": False}) + "\n"
    )
    monkeypatch.setattr("sys.argv", [
        "runner_actions", "--aggregate", str(tmp_path), "--out", str(tmp_path / "all.jsonl"),
    ])
    with pytest.raises(SystemExit) as exc:
        main()
    assert exc.value.code != 0


def test_aggregate_gold_run_exits_zero_when_all_resolved(tmp_path, monkeypatch):
    (tmp_path / "a.jsonl").write_text(
        json.dumps({"model": "gold", "resolved": True}) + "\n"
        + json.dumps({"model": "gold", "resolved": True}) + "\n"
    )
    monkeypatch.setattr("sys.argv", [
        "runner_actions", "--aggregate", str(tmp_path), "--out", str(tmp_path / "all.jsonl"),
    ])
    main()  # all resolved -> exit 0
