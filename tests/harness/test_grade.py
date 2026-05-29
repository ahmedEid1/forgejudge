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
from forgejudge.harness.runner_local import run_task_patch
from forgejudge.types import Task

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


def _patch_adding_files(instance_id: str, files: dict[str, str]) -> str:
    """Build a candidate patch that ADDS new ``files`` (path -> content) on top of
    base+test_patch, without touching any named test file."""
    src = source_dir_for(instance_id)
    tmp = Path(tempfile.mkdtemp(prefix="fjadd-"))
    try:
        copy_tree(src / "base", tmp)
        init_base_repo(tmp)
        apply_unified_diff(tmp, TASKS[instance_id].test_patch)
        git(tmp, "add", "-A")
        git(tmp, "commit", "-q", "-m", "base+test")
        for rel, content in files.items():
            (tmp / rel).parent.mkdir(parents=True, exist_ok=True)
            (tmp / rel).write_text(content)
        return staged_diff_against_base(tmp)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# --- Finding #7: candidate-added conftest/sitecustomize/plugins must not cheat ---

# conftest.py is auto-imported at pytest collection start, BEFORE the test module
# runs `from semver import compare`. This injects a fake `semver` into sys.modules
# so the buggy source is never executed — every oracle test passes without a fix.
# (Verified to fully resolve the task against the un-fixed runner.)
_SHADOW_CONFTEST = (
    "import sys, types\n"
    "_m = types.ModuleType('semver')\n"
    "def compare(a, b):\n"
    "    pa = [int(x) for x in a.split('.')]\n"
    "    pb = [int(x) for x in b.split('.')]\n"
    "    n = max(len(pa), len(pb))\n"
    "    pa += [0] * (n - len(pa)); pb += [0] * (n - len(pb))\n"
    "    return (pa > pb) - (pa < pb)\n"
    "_m.compare = compare\n"
    "sys.modules['semver'] = _m\n"
)


@pytest.mark.slow
def test_patch_cannot_cheat_with_added_conftest():
    # An added conftest.py that shadows the module-under-test must NOT let the
    # failing oracle masquerade as resolved — the candidate never fixed source.
    bad = _patch_adding_files(SEMVER, {"conftest.py": _SHADOW_CONFTEST})
    r = grade(TASKS[SEMVER], bad)
    assert r.resolved is False
    assert r.f2p_passed == 0  # the bug is still present; nothing was actually fixed


@pytest.mark.slow
def test_patch_cannot_cheat_with_added_pytest_plugin_conftest():
    # The same exploit also delivered via a conftest that registers a hook is
    # neutralized: any candidate-ADDED conftest.py is stripped before the oracle.
    plugin = _SHADOW_CONFTEST + (
        "\ndef pytest_collection_modifyitems(config, items):\n"
        "    for item in items:\n"
        "        item.add_marker(__import__('pytest').mark.skip(reason='cheat'))\n"
    )
    bad = _patch_adding_files(SEMVER, {"conftest.py": plugin})
    r = grade(TASKS[SEMVER], bad)
    assert r.resolved is False
    assert r.f2p_passed == 0


@pytest.mark.slow
def test_patch_cannot_cheat_with_added_sitecustomize():
    # sitecustomize.py / usercustomize.py are auto-imported by CPython's site
    # machinery; a candidate must not be able to smuggle one in to shadow or
    # monkeypatch the module under test. Stripped as defense-in-depth.
    bad = _patch_adding_files(SEMVER, {"sitecustomize.py": _SHADOW_CONFTEST})
    r = grade(TASKS[SEMVER], bad)
    assert r.resolved is False
    assert r.f2p_passed == 0


# --- Finding #35: a legit source fix in a file that ALSO holds an oracle node id
# (but is NOT touched by the test_patch) must be preserved. The old code reverted
# every node-id-prefix file unconditionally, clobbering such a fix; the test_patch
# is the correct thing to pin, not the node-id-prefix files. ---

def _shared_node_id_task(tmp: Path) -> Task:
    """A task whose SOURCE module also holds an in-module PASS_TO_PASS test, while
    the FAIL_TO_PASS test is added by the test_patch in a SEPARATE file.

    ``mod.py`` is therefore a node-id-prefix file (``mod.py::test_in_module``) yet
    the test_patch only touches ``test_mod.py`` — so a candidate fix to ``mod.py``
    must survive."""
    base = tmp / "base"
    base.mkdir(parents=True)
    # Buggy add(); an in-module test that passes on the buggy code too (5-0 == 5),
    # so it is a legitimate PASS_TO_PASS that lives inside the source module.
    (base / "mod.py").write_text(
        "def add(a, b):\n"
        "    return a - b  # BUG: should add\n\n\n"
        "def test_in_module():\n"
        "    assert add(5, 0) == 5\n"
    )
    # test_patch adds a SEPARATE file holding the failing oracle test.
    work = tmp / "work"
    copy_tree(base, work)
    init_base_repo(work)
    (work / "test_mod.py").write_text(
        "from mod import add\n\n\n"
        "def test_add_positive():\n"
        "    assert add(2, 3) == 5\n"
    )
    test_patch = staged_diff_against_base(work)
    return Task(
        instance_id="synthetic-shared-node-id",
        family="make_ci_green",
        repo="fixture:synthetic",
        base_commit="",
        problem_statement="add() subtracts instead of adding",
        test_patch=test_patch,
        fail_to_pass=["test_mod.py::test_add_positive"],
        pass_to_pass=["mod.py::test_in_module"],  # node-id prefix is the SOURCE file
        env_image="python:3.12-slim",
        source_license="own",
        created_at="2026-05-29",
    )


@pytest.mark.slow
def test_legit_fix_in_node_id_source_file_is_not_reverted():
    # mod.py is a pass_to_pass node-id-prefix file but is NOT touched by the
    # test_patch. The old node-id-prefix restore reverted mod.py to base, undoing
    # the candidate's source fix and mis-grading it as unresolved. The test_patch-
    # based restore must leave the source fix intact.
    tmp = Path(tempfile.mkdtemp(prefix="fjshared-"))
    try:
        task = _shared_node_id_task(tmp)
        work = tmp / "cand"
        copy_tree(tmp / "base", work)
        init_base_repo(work)
        apply_unified_diff(work, task.test_patch)
        git(work, "add", "-A")
        git(work, "commit", "-q", "-m", "base+test")
        # Candidate fixes only the source line in mod.py (a node-id file).
        (work / "mod.py").write_text(
            "def add(a, b):\n"
            "    return a + b  # FIXED\n\n\n"
            "def test_in_module():\n"
            "    assert add(5, 0) == 5\n"
        )
        candidate = staged_diff_against_base(work)
        outcome = run_task_patch(task, candidate, tmp)
        assert outcome.f2p_passed == outcome.f2p_total and outcome.f2p_total == 1
        assert outcome.p2p_passed == outcome.p2p_total and outcome.p2p_total == 1


    finally:
        shutil.rmtree(tmp, ignore_errors=True)


@pytest.mark.slow
def test_cheating_edit_to_test_patch_file_still_blocked():
    # The oracle file added by the test_patch is still pinned: a candidate that
    # neuters that test (without fixing source) must NOT resolve.
    tmp = Path(tempfile.mkdtemp(prefix="fjshared2-"))
    try:
        task = _shared_node_id_task(tmp)
        work = tmp / "cand"
        copy_tree(tmp / "base", work)
        init_base_repo(work)
        apply_unified_diff(work, task.test_patch)
        git(work, "add", "-A")
        git(work, "commit", "-q", "-m", "base+test")
        # Leave the bug in place but neuter the failing oracle test file.
        (work / "test_mod.py").write_text(
            "def test_add_positive():\n"
            "    pass  # neutered\n"
        )
        candidate = staged_diff_against_base(work)
        outcome = run_task_patch(task, candidate, tmp)
        assert outcome.f2p_passed == 0  # oracle restored; bug still present
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
