"""ForgeJudge's deterministic verdict must agree with the official swebench
grading rule, and the per-test pass/fail it is built from must reflect pytest's
*real* outcome (PASSED/SKIPPED/XFAIL/…) rather than the process exit code.

The equivalence tests require the optional ``forgejudge[harness]`` extra
(swebench); the core-correctness tests (#6 skip-as-pass, #8 timeout) do not and
run unconditionally.
"""

import shutil
import tempfile
import time
from pathlib import Path

import pytest

from forgejudge.golden.build_dataset import load_solutions, source_dir_for  # noqa: E402
from forgejudge.golden.loader import load_tasks  # noqa: E402
from forgejudge.golden.materialize import (  # noqa: E402
    copy_tree,
    init_base_repo,
    run_nodeids_status,
    run_nodeids_status_map,
    staged_diff_against_base,
)
from forgejudge.harness.runner_local import run_task_patch  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
TASKS = {t.instance_id: t for t in load_tasks(REPO_ROOT / "golden" / "dataset.jsonl")}
GOLD = load_solutions(REPO_ROOT / "golden" / "solutions.jsonl")
SEMVER = "fixture-semver-001"

pytestmark = [pytest.mark.slow, pytest.mark.swebench]


# --------------------------------------------------------------------------- #
# Finding #6 — SKIPPED tests must NOT be counted as PASSED (rc==0 is not a pass)
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "body",
    [
        # function-level skip on a test that WOULD fail if it ran
        "import pytest\n\n\n"
        "@pytest.mark.skip(reason='env changed')\n"
        "def test_oracle():\n    assert False\n",
        # module-level skip marker
        "import pytest\n\n"
        "pytestmark = pytest.mark.skip(reason='env changed')\n\n\n"
        "def test_oracle():\n    assert False\n",
        # runtime pytest.skip() (e.g. an importorskip that a patch can trigger)
        "import pytest\n\n\n"
        "def test_oracle():\n    pytest.skip('env changed')\n    assert False\n",
    ],
    ids=["marker-skip", "module-skip", "runtime-skip"],
)
def test_skipped_node_is_not_a_pass(body):
    """A SKIPPED oracle node exits pytest with rc==0; it must still read as NOT
    passed, otherwise a patch could fake a resolution by causing oracle tests to
    skip rather than run (swebench's test_passed excludes SKIPPED)."""
    tmp = Path(tempfile.mkdtemp(prefix="fjskip-"))
    try:
        (tmp / "test_oracle.py").write_text(body)
        status, _logs = run_nodeids_status(tmp, ["test_oracle.py::test_oracle"])
        assert status["test_oracle.py::test_oracle"] is False

        smap, _ = run_nodeids_status_map(tmp, ["test_oracle.py::test_oracle"])
        assert smap["test_oracle.py::test_oracle"] == "SKIPPED"
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_normal_pass_and_fail_unchanged():
    """The fix must not change ordinary pass/fail classification."""
    tmp = Path(tempfile.mkdtemp(prefix="fjpf-"))
    try:
        (tmp / "test_pf.py").write_text(
            "def test_ok():\n    assert True\n\n\n"
            "def test_bad():\n    assert False\n"
        )
        status, _ = run_nodeids_status(
            tmp, ["test_pf.py::test_ok", "test_pf.py::test_bad"]
        )
        assert status["test_pf.py::test_ok"] is True
        assert status["test_pf.py::test_bad"] is False
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_xfail_counts_as_pass_xpass_strict_does_not():
    """Mirror swebench: XFAIL is a pass; a strict XPASS (reported as a failure) is
    not. A non-strict xpass shows up as plain passed, also a pass."""
    tmp = Path(tempfile.mkdtemp(prefix="fjxf-"))
    try:
        (tmp / "test_xf.py").write_text(
            "import pytest\n\n\n"
            "@pytest.mark.xfail\n"
            "def test_xfail():\n    assert False\n\n\n"
            "@pytest.mark.xfail(strict=True)\n"
            "def test_xpass_strict():\n    assert True\n"
        )
        smap, _ = run_nodeids_status_map(
            tmp, ["test_xf.py::test_xfail", "test_xf.py::test_xpass_strict"]
        )
        assert smap["test_xf.py::test_xfail"] == "XFAIL"
        status, _ = run_nodeids_status(
            tmp, ["test_xf.py::test_xfail", "test_xf.py::test_xpass_strict"]
        )
        assert status["test_xf.py::test_xfail"] is True
        assert status["test_xf.py::test_xpass_strict"] is False
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_missing_or_deselected_node_is_not_a_pass():
    """A node id that selects nothing ('no tests ran', rc==5) must read as NOT
    passed rather than being silently counted as a pass."""
    tmp = Path(tempfile.mkdtemp(prefix="fjmiss-"))
    try:
        (tmp / "test_m.py").write_text("def test_present():\n    assert True\n")
        status, _ = run_nodeids_status(tmp, ["test_m.py::test_absent"])
        assert status["test_m.py::test_absent"] is False
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# --------------------------------------------------------------------------- #
# Finding #8 — a hanging candidate must be bounded by a per-node timeout
# --------------------------------------------------------------------------- #


def test_infinite_loop_node_times_out_and_is_not_a_pass():
    """An infinite-loop test must be reaped by the per-node timeout and recorded
    as NOT passed — not hang the grader forever."""
    tmp = Path(tempfile.mkdtemp(prefix="fjhang-"))
    try:
        (tmp / "test_hang.py").write_text(
            "def test_spin():\n    while True:\n        pass\n"
        )
        t0 = time.monotonic()
        status, logs = run_nodeids_status(
            tmp, ["test_hang.py::test_spin"], timeout=3
        )
        elapsed = time.monotonic() - t0
        assert status["test_hang.py::test_spin"] is False
        assert elapsed < 30, f"timeout did not bound wall clock: {elapsed:.1f}s"
        assert "[timeout" in logs
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# --------------------------------------------------------------------------- #
# Finding #22 — drive the swebench equivalence check from REAL per-node statuses
# --------------------------------------------------------------------------- #


def _break_p2p_patch() -> str:
    tmp = Path(tempfile.mkdtemp(prefix="fjswe-"))
    try:
        copy_tree(source_dir_for(SEMVER) / "base", tmp)
        init_base_repo(tmp)
        (tmp / "semver.py").write_text("def compare(a, b):\n    return 0\n")
        return staged_diff_against_base(tmp)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


@pytest.mark.parametrize(
    ("patch_fn", "expected_resolved"),
    [
        (lambda: GOLD[SEMVER], True),
        (lambda: "", False),
        (_break_p2p_patch, False),
    ],
)
def test_our_verdict_matches_official_swebench(patch_fn, expected_resolved):
    pytest.importorskip("swebench")
    from forgejudge.harness.swebench_grade import is_resolved_by_swebench

    task = TASKS[SEMVER]
    outcome = run_task_patch(task, patch_fn(), source_dir_for(SEMVER))
    ours = (
        outcome.f2p_passed == outcome.f2p_total
        and outcome.p2p_passed == outcome.p2p_total
    )
    # outcome.status_map now carries pytest's real per-node verdicts (parsed from
    # junit), so feeding it to the official swebench grading is a genuine
    # cross-check rather than re-grading ForgeJudge's own rc heuristic.
    official = is_resolved_by_swebench(task, outcome.status_map)
    assert ours == official == expected_resolved


def test_forgejudge_is_stricter_than_swebench_on_skipped_f2p():
    """ForgeJudge deliberately diverges from — and is stricter than — the official
    swebench grading on a SKIPPED FAIL_TO_PASS node.

    Empirically (swebench 4.1.0), a SKIPPED test is neither a ``success`` nor a
    ``failure`` in ``get_eval_tests_report``; with an empty failure list the run is
    rated ``RESOLVED_FULL``. So a candidate that makes the oracle FAIL_TO_PASS tests
    *skip* (rather than run) is graded RESOLVED by swebench — a silent cheat vector.

    ForgeJudge closes that gap: a node passes ONLY when pytest reports PASSED/XFAIL
    (``_PASSING_STATUSES``), so a skipped FAIL_TO_PASS is not-passed and the task is
    unresolved. This test pins both sides of the divergence so neither can drift."""
    pytest.importorskip("swebench")
    from forgejudge.golden.materialize import _PASSING_STATUSES
    from forgejudge.harness.swebench_grade import is_resolved_by_swebench

    task = TASKS[SEMVER]
    status_map = dict.fromkeys(task.pass_to_pass, "PASSED")
    status_map.update(dict.fromkeys(task.fail_to_pass, "SKIPPED"))

    # Official swebench is lenient here — it rates a skipped f2p RESOLVED_FULL.
    assert is_resolved_by_swebench(task, status_map) is True
    # ForgeJudge's rule (a node passes iff PASSED/XFAIL) treats the skip as a miss,
    # so the FAIL_TO_PASS set is not satisfied and the run is unresolved.
    fj_f2p_passed = all(status_map[n] in _PASSING_STATUSES for n in task.fail_to_pass)
    assert fj_f2p_passed is False
