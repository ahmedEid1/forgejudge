"""Owned golden tasks (mined from Ahmed's own repos) must be well-formed AND
intrinsically verifiable.

Each task under ``golden/owned/`` carries real provenance — the ``repo`` slug is
one of Ahmed's own GitHub repos (``ahmedEid1/...``, ``source_license: own``,
zero license risk) pinned to a concrete ``base_commit`` — and the same
buggy-base/gold-fix invariants the fixtures satisfy: every FAIL_TO_PASS test
fails on the buggy base, every PASS_TO_PASS test passes on it, and the gold fix
turns everything green without regressions.
"""

import pytest

from forgejudge.golden.build_dataset import (
    OWNED_ROOT,
    build_task,
    discover_task_dirs,
    validate_task,
)

OWNED_TASK_DIRS = [
    d for d in discover_task_dirs() if OWNED_ROOT in d.parents
]


def test_at_least_two_owned_tasks_exist():
    assert len(OWNED_TASK_DIRS) >= 2, (
        f"expected >=2 owned tasks under {OWNED_ROOT}, found {len(OWNED_TASK_DIRS)}"
    )


@pytest.mark.parametrize(
    "task_dir", OWNED_TASK_DIRS, ids=[d.name for d in OWNED_TASK_DIRS]
)
def test_owned_task_provenance(task_dir):
    task, _gold = build_task(task_dir)
    assert task.source_license == "own"
    assert task.repo.startswith("ahmedEid1/"), (
        f"{task.instance_id}: repo {task.repo!r} is not an ahmedEid1 slug"
    )
    assert task.base_commit.strip(), f"{task.instance_id}: base_commit is empty"


@pytest.mark.slow
@pytest.mark.parametrize(
    "task_dir", OWNED_TASK_DIRS, ids=[d.name for d in OWNED_TASK_DIRS]
)
def test_owned_task_is_intrinsically_verifiable(task_dir):
    task, gold = build_task(task_dir)
    assert task.fail_to_pass, "must declare >=1 FAIL_TO_PASS test"
    assert task.pass_to_pass, "must declare >=1 PASS_TO_PASS test"
    assert task.test_patch.strip(), "test_patch must be non-empty"
    assert gold.strip(), "gold_patch must be non-empty"

    v = validate_task(task, gold, task_dir)
    assert v.buggy_f2p_passed == 0, f"f2p must FAIL on buggy base:\n{v.logs}"
    assert v.buggy_p2p_passed == v.p2p_total, f"p2p must pass on base:\n{v.logs}"
    assert v.golden_f2p_passed == v.f2p_total, f"gold fix must make f2p PASS:\n{v.logs}"
    assert v.golden_p2p_passed == v.p2p_total, f"gold fix must not break p2p:\n{v.logs}"
    assert v.is_valid
