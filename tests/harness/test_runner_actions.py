"""The sandbox grade executor: gold patches resolve every task, empty patches
resolve none, sharding partitions the set, and aggregation concatenates."""

from pathlib import Path

import pytest

from forgejudge.golden.build_dataset import load_solutions
from forgejudge.golden.loader import load_tasks
from forgejudge.harness.runner_actions import aggregate, grade_tasks, select_shard

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
