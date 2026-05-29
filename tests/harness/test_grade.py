"""The deterministic scorer: a patch resolves a task iff every FAIL_TO_PASS test
goes green AND every PASS_TO_PASS test stays green (the official SWE-bench rule).
"""

import shutil
import tempfile
from pathlib import Path

import pytest

from forgejudge.golden.build_dataset import load_solutions, source_dir_for
from forgejudge.golden.loader import load_tasks
from forgejudge.golden.materialize import (
    apply_unified_diff,
    copy_tree,
    git,
    init_base_repo,
    staged_diff_against_base,
)
from forgejudge.harness.grade import grade

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
TASKS = {t.instance_id: t for t in load_tasks(REPO_ROOT / "golden" / "dataset.jsonl")}
GOLD = load_solutions(REPO_ROOT / "golden" / "solutions.jsonl")
SEMVER = "fixture-semver-001"


def _patch_replacing(instance_id: str, rel: str, new_content: str) -> str:
    """Build a candidate patch that overwrites ``rel`` with ``new_content``."""
    src = source_dir_for(instance_id)
    tmp = Path(tempfile.mkdtemp(prefix="fjmkpatch-"))
    try:
        copy_tree(src / "base", tmp)
        init_base_repo(tmp)
        (tmp / rel).write_text(new_content)
        return staged_diff_against_base(tmp)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


@pytest.mark.slow
def test_gold_patch_resolves():
    r = grade(TASKS[SEMVER], GOLD[SEMVER])
    assert r.resolved is True
    assert r.f2p_passed == r.f2p_total and r.f2p_total > 0
    assert r.p2p_passed == r.p2p_total and r.p2p_total > 0


@pytest.mark.slow
def test_empty_patch_does_not_resolve():
    r = grade(TASKS[SEMVER], "")
    assert r.resolved is False
    assert r.f2p_passed == 0  # the bug is still present


@pytest.mark.slow
def test_patch_breaking_pass_to_pass_does_not_resolve():
    # compare() that always returns 0: the FAIL_TO_PASS tests won't pass and the
    # PASS_TO_PASS ordering tests regress.
    bad = _patch_replacing(SEMVER, "semver.py", "def compare(a, b):\n    return 0\n")
    r = grade(TASKS[SEMVER], bad)
    assert r.resolved is False
    assert r.p2p_passed < r.p2p_total  # a PASS_TO_PASS test regressed


@pytest.mark.slow
def test_malformed_patch_is_unresolved_not_crash():
    r = grade(TASKS[SEMVER], "this is not a valid diff\n@@ garbage @@\n")
    assert r.resolved is False
    # tests still ran against base+test_patch (bug present)
    assert r.f2p_total > 0


@pytest.mark.slow
def test_gold_patch_resolves_an_owned_task():
    iid = "owned-handson-metrics"
    r = grade(TASKS[iid], GOLD[iid])
    assert r.resolved is True


def _patch_modifying_testfile(instance_id: str, rel: str, new_content: str) -> str:
    """Build a candidate that modifies a test file as it exists AFTER test_patch."""
    src = source_dir_for(instance_id)
    tmp = Path(tempfile.mkdtemp(prefix="fjcheat-"))
    try:
        copy_tree(src / "base", tmp)
        init_base_repo(tmp)
        apply_unified_diff(tmp, TASKS[instance_id].test_patch)
        git(tmp, "add", "-A")
        git(tmp, "commit", "-q", "-m", "base+test")
        (tmp / rel).write_text(new_content)
        return staged_diff_against_base(tmp)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


@pytest.mark.slow
def test_patch_cannot_cheat_by_neutering_the_test():
    # A patch that overwrites the FAIL_TO_PASS test to trivially pass, WITHOUT
    # fixing the source, must NOT resolve — the canonical test is restored.
    neutered = (
        "def test_double_digit_minor():\n    pass\n\n\n"
        "def test_double_digit_symmetry():\n    pass\n\n\n"
        "def test_shorter_version_equals_zero_padded():\n    pass\n"
    )
    bad = _patch_modifying_testfile(SEMVER, "test_semver_bug.py", neutered)
    r = grade(TASKS[SEMVER], bad)
    assert r.resolved is False
