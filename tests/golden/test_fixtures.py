"""Every fixture must be intrinsically verifiable: the FAIL_TO_PASS test must
actually FAIL on the buggy base and PASS after the gold fix, while PASS_TO_PASS
tests stay green. Proven by running pytest in a materialized tree."""

import pytest

from forgejudge.golden.build_dataset import build_task, discover_task_dirs, validate_task

TASK_DIRS = discover_task_dirs()


def test_at_least_one_fixture_exists():
    assert len(TASK_DIRS) >= 1


@pytest.mark.slow
@pytest.mark.parametrize("task_dir", TASK_DIRS, ids=[d.name for d in TASK_DIRS])
def test_fixture_is_intrinsically_verifiable(task_dir):
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
