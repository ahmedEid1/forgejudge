"""The deterministic scorer.

``grade(task, patch)`` returns a :class:`GradeResult` whose ``resolved`` is True
iff every FAIL_TO_PASS test transitions to passing AND every PASS_TO_PASS test
stays passing — the exact SWE-bench ``get_resolution_status == FULL`` rule. The
agent is stochastic; this scorer is not.
"""

from pathlib import Path

from forgejudge.golden.build_dataset import source_dir_for
from forgejudge.harness.runner_local import run_task_patch
from forgejudge.types import GradeResult, Task


def grade(task: Task, patch: str, *, source_dir: str | Path | None = None) -> GradeResult:
    """Apply ``patch`` in the task's pinned environment and score it.

    ``source_dir`` defaults to the task's bundled directory (located by
    ``instance_id``); pass it explicitly to grade out-of-tree checkouts.
    """
    src = Path(source_dir) if source_dir is not None else source_dir_for(task.instance_id)
    outcome = run_task_patch(task, patch, src)
    return GradeResult(
        f2p_passed=outcome.f2p_passed,
        f2p_total=outcome.f2p_total,
        p2p_passed=outcome.p2p_passed,
        p2p_total=outcome.p2p_total,
        logs=outcome.logs,
    )
