"""Cross-check ForgeJudge's verdict against the *official* swebench grading.

ForgeJudge encodes the SWE-bench resolution rule directly (``GradeResult.resolved``)
so the core scorer has no heavy runtime dependency. To keep that claim honest, we
also map a per-test status into ``swebench.harness.grading`` and assert the two
agree (see tests/harness/test_swebench_grade.py). ``swebench`` is an optional
extra (``forgejudge[harness]``); import it lazily.
"""

from forgejudge.types import Task


def swebench_resolution_status(task: Task, status_map: dict[str, str]) -> str:
    """Return swebench's ``RESOLVED_FULL`` / ``RESOLVED_PARTIAL`` / ``RESOLVED_NO``.

    ``status_map`` maps each FAIL_TO_PASS/PASS_TO_PASS node id to a
    ``swebench`` ``TestStatus`` value ("PASSED" / "FAILED").
    """
    from swebench.harness.constants import FAIL_TO_PASS, PASS_TO_PASS
    from swebench.harness.grading import get_eval_tests_report, get_resolution_status

    gold_results = {
        FAIL_TO_PASS: list(task.fail_to_pass),
        PASS_TO_PASS: list(task.pass_to_pass),
    }
    report = get_eval_tests_report(status_map, gold_results)
    return get_resolution_status(report)


def is_resolved_by_swebench(task: Task, status_map: dict[str, str]) -> bool:
    """True iff the official swebench grading rates the run ``RESOLVED_FULL``."""
    from swebench.harness.constants import ResolvedStatus

    return swebench_resolution_status(task, status_map) == ResolvedStatus.FULL.value
