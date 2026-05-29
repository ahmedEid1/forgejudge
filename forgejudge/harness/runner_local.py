"""Local runner: materialize a task, apply a candidate patch, run its tests.

Used directly inside the GitHub Actions ephemeral VM (which is itself the
sandbox boundary — see the design's "$0 sandbox" insight). A Docker runner with
the same interface provides defense-in-depth where available.
"""

import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path

from forgejudge.golden.materialize import (
    apply_unified_diff,
    copy_tree,
    git,
    init_base_repo,
    run_nodeids,
)
from forgejudge.types import Task


@dataclass
class RunOutcome:
    f2p_passed: int
    f2p_total: int
    p2p_passed: int
    p2p_total: int
    logs: str


def run_task_patch(task: Task, patch: str, source_dir: str | Path) -> RunOutcome:
    """Apply ``test_patch`` then the candidate ``patch`` to a fresh copy of the
    task's base tree and run the FAIL_TO_PASS + PASS_TO_PASS tests.

    A candidate patch that fails to apply leaves the tree at base+test_patch
    (so the task is simply unresolved, never a crash or a half-applied tree).
    """
    source_dir = Path(source_dir)
    tmp = Path(tempfile.mkdtemp(prefix=f"fjrun-{task.instance_id}-"))
    patch_note = ""
    try:
        copy_tree(source_dir / "base", tmp)
        init_base_repo(tmp)

        # Apply the test_patch and commit, so 'base + test_patch' is a clean
        # checkpoint a failed candidate patch can be reset back to.
        apply_unified_diff(tmp, task.test_patch)
        git(tmp, "add", "-A")
        git(tmp, "commit", "-q", "-m", "test_patch", "--allow-empty")

        try:
            apply_unified_diff(tmp, patch)
        except RuntimeError as exc:
            patch_note = f"[candidate patch did not apply: {exc}]"
            git(tmp, "reset", "-q", "--hard", "HEAD")
            git(tmp, "clean", "-qfd")

        f2p_passed, f2p_total, l1 = run_nodeids(tmp, task.fail_to_pass)
        p2p_passed, p2p_total, l2 = run_nodeids(tmp, task.pass_to_pass)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    logs = "\n".join(filter(None, [patch_note, "[FAIL_TO_PASS]", l1, "[PASS_TO_PASS]", l2]))
    return RunOutcome(f2p_passed, f2p_total, p2p_passed, p2p_total, logs)
