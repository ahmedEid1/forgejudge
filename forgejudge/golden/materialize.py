"""Materialize a task's working tree and apply patches deterministically.

A fixture is three plain directory states under ``fixtures/<name>/``:

* ``base/`` — the repo at base_commit: BUGGY source + existing PASSING tests.
* ``test/`` — the file(s) the ``test_patch`` introduces (the failing test).
* ``fix/``  — the corrected source (the reference / "gold" solution).

Unified diffs (``test_patch``, ``gold_patch``) are *derived* from these states
with git, so authors never hand-write diffs. Patch application also goes through
git (``git apply``, with a 3-way fallback), mirroring the SWE-bench harness.
"""

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

_GIT_ENV = [
    "-c",
    "user.email=harness@forgejudge.local",
    "-c",
    "user.name=forgejudge-harness",
    "-c",
    "commit.gpgsign=false",
    "-c",
    "core.autocrlf=false",
]


def git(workdir: str | Path, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    """Run git in ``workdir`` with a pinned identity."""
    return subprocess.run(
        ["git", *_GIT_ENV, *args],
        cwd=str(workdir),
        capture_output=True,
        text=True,
        check=check,
    )


def copy_tree(src: str | Path, dst: str | Path) -> None:
    """Overlay ``src`` onto ``dst`` (files merged, existing files overwritten)."""
    shutil.copytree(src, dst, dirs_exist_ok=True)


def init_base_repo(workdir: str | Path) -> None:
    """Initialize a throwaway git repo and commit the current tree as 'base'."""
    git(workdir, "init", "-q")
    git(workdir, "add", "-A")
    git(workdir, "commit", "-q", "-m", "base", "--allow-empty")


def apply_unified_diff(workdir: str | Path, diff_text: str) -> None:
    """Apply ``diff_text`` in ``workdir`` via ``git apply`` (3-way fallback).

    Raises ``RuntimeError`` with git's stderr if the patch does not apply.
    """
    if not diff_text.strip():
        return
    with tempfile.NamedTemporaryFile("w", suffix=".diff", delete=False) as fh:
        fh.write(diff_text if diff_text.endswith("\n") else diff_text + "\n")
        patch_path = fh.name
    try:
        for extra in (["-p1"], ["-p1", "--3way"], ["-p0"]):
            res = git(workdir, "apply", "--whitespace=nowarn", *extra, patch_path, check=False)
            if res.returncode == 0:
                return
        raise RuntimeError(f"patch did not apply:\n{res.stderr}")
    finally:
        Path(patch_path).unlink(missing_ok=True)


def staged_diff_against_base(workdir: str | Path) -> str:
    """Stage all changes and return the unified diff vs the base commit."""
    git(workdir, "add", "-A")
    return git(workdir, "diff", "--cached", "--no-color").stdout


def reset_to_base(workdir: str | Path) -> None:
    """Discard all changes (tracked + untracked) back to the base commit."""
    git(workdir, "reset", "-q", "--hard", "HEAD")
    git(workdir, "clean", "-qfd")


def run_nodeids(
    workdir: str | Path, nodeids: list[str], *, python: str | None = None
) -> tuple[int, int, str]:
    """Run each pytest node id in ``workdir`` and count how many pass.

    Each node id is run in its own pytest process so the pass/fail verdict is
    exact and independent. Returns ``(passed, total, combined_logs)``.
    """
    python = python or sys.executable
    passed = 0
    logs: list[str] = []
    for nodeid in nodeids:
        res = subprocess.run(
            [python, "-m", "pytest", nodeid, "-q", "--no-header", "-p", "no:cacheprovider"],
            cwd=str(workdir),
            capture_output=True,
            text=True,
            check=False,
        )
        ok = res.returncode == 0
        passed += int(ok)
        logs.append(f"$ pytest {nodeid} -> rc={res.returncode} ({'PASS' if ok else 'FAIL'})")
        logs.append(res.stdout[-2000:])
    return passed, len(nodeids), "\n".join(logs)
