"""Snapshot-and-inject helper for mining ``make_ci_green`` tasks from owned repos.

This module records (and partially automates) the manual flow used to turn a
self-contained pure-Python utility from one of Ahmed's own repositories into a
ForgeJudge golden task under ``golden/owned/<name>/``.

The golden-task layout (identical to ``forgejudge/golden/fixtures/semver-001``)::

    golden/owned/<name>/
        meta.yaml   # instance_id / repo / base_commit / problem_statement / ...
        base/       # the source module(s) WITH an injected bug + a PASSING test
        test/       # a NEW test file that FAILS on the buggy base (FAIL_TO_PASS)
        fix/         # the ORIGINAL, correct module(s) (the gold solution)

The build/validate harness (``forgejudge.golden.build_dataset``) derives the
``test_patch`` and ``gold_patch`` from these three directory states with git and
proves the invariants by actually running pytest:

* every FAIL_TO_PASS test FAILS on ``base/`` + ``test/`` (the bug is real), and
* every PASS_TO_PASS test PASSES on ``base/`` (the existing behaviour is intact),
* after applying ``fix/`` ALL tests pass (the gold fix is correct & complete).

Provenance contract for an owned task's ``meta.yaml``:
    * ``repo``        — the real slug, e.g. ``ahmedEid1/Hands-On-Large-Language-Models``
                        (from ``git -C <repo> remote get-url origin``).
    * ``base_commit`` — ``git -C <repo> rev-parse HEAD`` of the source clone.
    * ``source_license: own`` (Ahmed's own repos — zero license risk).
    * a top-of-file YAML comment recording the source file path + function(s).

This file is a clear, documented utility rather than a full miner: the human
authoring the task chooses the function, ports/authors the tests, and decides the
realistic bug. The helpers below remove the mechanical, error-prone parts
(reading provenance, snapshotting the source file flat so its import name matches
its filename, and scaffolding the directory).
"""

from __future__ import annotations

import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
OWNED_ROOT = REPO_ROOT / "golden" / "owned"


def _git(repo: Path, *args: str) -> str:
    """Run ``git -C <repo> <args>`` and return stripped stdout."""
    out = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        check=True,
    )
    return out.stdout.strip()


def _slug_from_url(url: str) -> str:
    """Parse the ``owner/name`` slug from any common git remote URL form.

    Handles HTTPS (``https://github.com/owner/name.git``), SCP/SSH
    (``git@github.com:owner/name.git`` — owner is separated from host by ``:``,
    not ``/``), and bare/nested paths uniformly: strip a trailing ``.git``, then
    take the last two path components after splitting on BOTH ``/`` and ``:``
    (Finding #32 — ``rsplit('/')`` mis-parsed the SCP/SSH form).
    """
    parts = [p for p in re.split(r"[/:]", url.strip().removesuffix(".git")) if p]
    return "/".join(parts[-2:])


def repo_slug(repo: str | Path) -> str:
    """Return the ``owner/name`` slug from a clone's ``origin`` remote.

    ``https://github.com/ahmedEid1/thoth.git`` -> ``ahmedEid1/thoth``;
    ``git@github.com:ahmedEid1/thoth.git`` -> ``ahmedEid1/thoth``.
    """
    return _slug_from_url(_git(Path(repo), "remote", "get-url", "origin"))


def repo_head(repo: str | Path) -> str:
    """Return the current HEAD SHA of a clone (the task's ``base_commit``)."""
    return _git(Path(repo), "rev-parse", "HEAD")


@dataclass(frozen=True)
class Provenance:
    """Where an owned task's source code came from (for meta.yaml + audit)."""

    repo: str          # ahmedEid1/<name>
    base_commit: str   # source HEAD SHA
    source_path: str   # path to the file inside the source repo
    functions: str     # human note: which function(s)/class(es) were used

    def as_yaml_comment(self) -> str:
        """Render the provenance block placed at the top of ``meta.yaml``."""
        return (
            "# Provenance\n"
            f"#   repo:        {self.repo}\n"
            f"#   base_commit: {self.base_commit}\n"
            f"#   source file: {self.source_path}\n"
            f"#   functions:   {self.functions}\n"
        )


def gather_provenance(repo: str | Path, source_path: str, functions: str) -> Provenance:
    """Read the live provenance (slug + HEAD) for a source file in a clone."""
    repo = Path(repo)
    if not (repo / source_path).is_file():
        raise FileNotFoundError(f"{source_path!r} not found in {repo}")
    return Provenance(
        repo=repo_slug(repo),
        base_commit=repo_head(repo),
        source_path=source_path,
        functions=functions,
    )


def snapshot_source(repo: str | Path, source_path: str, dest_dir: Path) -> Path:
    """Copy a single source file *flat* into ``dest_dir``.

    Golden tasks materialize ``base/`` (and ``fix/``) as the repo root, so a test
    imports the module by its *bare filename* (``from metrics import ...``). The
    file is therefore snapshotted by basename, dropping the package path.
    Returns the destination path.
    """
    src = Path(repo) / source_path
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / src.name
    shutil.copyfile(src, dest)
    return dest


def scaffold_task(name: str, *, owned_root: Path = OWNED_ROOT) -> dict[str, Path]:
    """Create ``golden/owned/<name>/{base,test,fix}`` and return the paths.

    Does not overwrite an existing task directory's files; just ensures the
    three sub-directories exist. The author then snapshots the source into
    ``fix/`` and ``base/`` (via :func:`snapshot_source`), injects a realistic bug
    into ``base/``, writes the passing test into ``base/`` and the failing test
    into ``test/``, and writes ``meta.yaml``.
    """
    task_dir = owned_root / name
    paths = {
        "task": task_dir,
        "base": task_dir / "base",
        "test": task_dir / "test",
        "fix": task_dir / "fix",
    }
    for key in ("base", "test", "fix"):
        paths[key].mkdir(parents=True, exist_ok=True)
    return paths


def snapshot_pair(repo: str | Path, source_path: str, task_paths: dict[str, Path]) -> Path:
    """Snapshot a source file into BOTH ``fix/`` and ``base/`` of a task.

    Convenience for the common case: the original (correct) code goes to ``fix/``
    and a starting copy goes to ``base/`` for the author to inject a bug into.
    Returns the ``base/`` destination path (the one the author edits).
    """
    snapshot_source(repo, source_path, task_paths["fix"])
    return snapshot_source(repo, source_path, task_paths["base"])
