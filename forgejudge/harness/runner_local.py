"""Local runner: materialize a task, apply a candidate patch, run its tests.

Used directly inside the GitHub Actions ephemeral VM (which is itself the
sandbox boundary — see the design's "$0 sandbox" insight). A Docker runner with
the same interface provides defense-in-depth where available.
"""

import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from forgejudge.golden.materialize import (
    apply_unified_diff,
    copy_tree,
    git,
    init_base_repo,
    run_nodeids_status,
)
from forgejudge.types import Task

# Files pytest / CPython auto-load by *name* regardless of the named test files.
# A candidate that ADDS or MODIFIES one of these can register collection hooks,
# autouse fixtures, or sys.modules shadows that fake a FAIL->PASS transition
# without touching source, so they are reverted/removed before the oracle runs.
_AUTOLOAD_BASENAMES = frozenset({
    "conftest.py",
    "sitecustomize.py",
    "usercustomize.py",
})


def _is_autoload_path(path: str) -> bool:
    """True if ``path``'s basename is an auto-imported pytest/CPython hook file."""
    return Path(path).name in _AUTOLOAD_BASENAMES


def _test_patch_paths(workdir: str | Path, test_patch: str) -> list[str]:
    """The repo-relative paths the ``test_patch`` touches (via ``git apply --numstat``).

    These are test-only by construction, so resetting them to HEAD pins the oracle
    without clobbering a legitimate candidate source edit that happens to live in
    the same file (see finding #35)."""
    if not test_patch.strip():
        return []
    res = subprocess.run(
        ["git", "apply", "--numstat", "--whitespace=nowarn", "-p1"],
        input=test_patch if test_patch.endswith("\n") else test_patch + "\n",
        cwd=str(workdir),
        capture_output=True,
        text=True,
        check=False,
    )
    paths: list[str] = []
    for line in res.stdout.splitlines():
        parts = line.split("\t")
        if len(parts) == 3 and parts[2]:
            # A rename shows as "old => new"; the touched test file is the new name.
            name = parts[2].split(" => ")[-1].strip("{}")
            paths.append(name)
    return paths


def _strip_candidate_autoload_files(workdir: str | Path) -> None:
    """Revert/remove any auto-loaded hook file the candidate added or changed.

    Compares the working tree against HEAD (base+test_patch). A candidate
    *added* conftest.py / sitecustomize.py / usercustomize.py is deleted; a
    *modified* (or deleted/renamed) one is restored to its HEAD version, so the
    oracle always runs against the pinned auto-load machinery."""
    git(workdir, "add", "-A", check=False)
    diff = git(workdir, "diff", "--cached", "--name-status", "HEAD", check=False).stdout
    for line in diff.splitlines():
        parts = line.split("\t")
        if len(parts) < 2:
            continue
        status = parts[0]
        # Rename/copy lines are "Rxxx\told\tnew"; check both the old and new path.
        candidate_paths = parts[1:] if status[0] in {"R", "C"} else parts[1:2]
        for path in candidate_paths:
            if not _is_autoload_path(path):
                continue
            head = git(workdir, "cat-file", "-e", f"HEAD:{path}", check=False)
            if head.returncode == 0:
                # Existed at HEAD: restore the pinned version (undo any edit).
                git(workdir, "checkout", "HEAD", "--", path, check=False)
            else:
                # Candidate-added: remove it entirely.
                (Path(workdir) / path).unlink(missing_ok=True)


@dataclass
class RunOutcome:
    f2p_passed: int
    f2p_total: int
    p2p_passed: int
    p2p_total: int
    logs: str
    # nodeid -> "PASSED"/"FAILED"; fed to the official swebench grading for the
    # equivalence check (see harness/swebench_grade.py).
    status_map: dict[str, str] = field(default_factory=dict)


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

        # Cheat-resistance (mirrors SWE-bench: keep the model's source diff but
        # discard any change it made to the oracle). The candidate may only
        # change SOURCE, never the tests or pytest's auto-loaded machinery:
        #
        #   1. Reset every path the test_patch touches back to HEAD. These are
        #      test-only by construction, so this pins the oracle while PRESERVING
        #      a legitimate source edit that shares a file with a test (#35) —
        #      unlike the old node-id-prefix allowlist, which reverted the whole
        #      shared file.
        #   2. Strip/revert any conftest.py / sitecustomize.py / usercustomize.py
        #      the candidate ADDED or MODIFIED. Such files are auto-imported by
        #      pytest/CPython and can register hooks, autouse fixtures, or
        #      sys.modules shadows that fake a FAIL->PASS without fixing source
        #      (#7) even though they are not among the named test files.
        for tf in _test_patch_paths(tmp, task.test_patch):
            git(tmp, "checkout", "HEAD", "--", tf, check=False)
        _strip_candidate_autoload_files(tmp)

        f2p_status, l1 = run_nodeids_status(tmp, task.fail_to_pass)
        p2p_status, l2 = run_nodeids_status(tmp, task.pass_to_pass)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    status_map = {
        nodeid: ("PASSED" if ok else "FAILED")
        for nodeid, ok in {**f2p_status, **p2p_status}.items()
    }
    logs = "\n".join(filter(None, [patch_note, "[FAIL_TO_PASS]", l1, "[PASS_TO_PASS]", l2]))
    return RunOutcome(
        f2p_passed=sum(f2p_status.values()),
        f2p_total=len(f2p_status),
        p2p_passed=sum(p2p_status.values()),
        p2p_total=len(p2p_status),
        logs=logs,
        status_map=status_map,
    )
