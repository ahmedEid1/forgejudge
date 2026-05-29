"""Hermetic, network-free tests for the owned-repo mining helpers.

These drive ``forgejudge.golden.mine_owned`` end-to-end against a *throwaway*
git repository created in ``tmp_path`` (``git init`` -> write files -> commit a
"bug" then a "fix" with real SHAs), with its ``origin`` remote pointed at a
github-style URL. No network, no LLM, no database: only local git.

The ``_slug_from_url`` parser (HTTPS + SSH forms) is already covered by
``tests/golden/test_loader.py`` and ``tests/golden/test_owned_tasks.py`` is left
untouched; this file targets the function-level entry points and edge branches.
"""

from __future__ import annotations

import subprocess

import pytest

from forgejudge.golden import mine_owned
from forgejudge.golden.mine_owned import (
    Provenance,
    gather_provenance,
    repo_head,
    repo_slug,
    scaffold_task,
    snapshot_pair,
    snapshot_source,
)


def _run(repo, *args):
    subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
    )


@pytest.fixture
def git_repo(tmp_path):
    """A throwaway git repo with two real commits (a "bug" then a "fix").

    Returns a dict carrying the repo path plus the two real commit SHAs and the
    relative source path that exists at HEAD.
    """
    repo = tmp_path / "clone"
    repo.mkdir()
    _run(repo, "init", "-q")
    _run(repo, "config", "user.email", "test@example.com")
    _run(repo, "config", "user.name", "Test")
    _run(repo, "config", "commit.gpgsign", "false")

    pkg = repo / "src" / "mypkg"
    pkg.mkdir(parents=True)
    source_rel = "src/mypkg/metrics.py"

    # Commit 1: the buggy version.
    (repo / source_rel).write_text("def add(a, b):\n    return a - b  # bug\n")
    _run(repo, "add", "-A")
    _run(repo, "commit", "-q", "-m", "buggy add")
    bug_sha = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()

    # Commit 2: the fix (this is HEAD).
    (repo / source_rel).write_text("def add(a, b):\n    return a + b\n")
    _run(repo, "add", "-A")
    _run(repo, "commit", "-q", "-m", "fix add")
    fix_sha = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()

    return {
        "repo": repo,
        "source_rel": source_rel,
        "bug_sha": bug_sha,
        "fix_sha": fix_sha,
    }


# --- _git (lines 51-57) via repo_slug / repo_head --------------------------


def test_repo_slug_reads_https_origin(git_repo):
    """repo_slug runs real git remote get-url + _slug_from_url end-to-end."""
    repo = git_repo["repo"]
    _run(repo, "remote", "add", "origin", "https://github.com/ahmedEid1/metrics.git")
    assert repo_slug(repo) == "ahmedEid1/metrics"


def test_repo_slug_reads_ssh_origin(git_repo):
    """The SCP/SSH remote form must yield owner/name, not host:owner/name."""
    repo = git_repo["repo"]
    _run(repo, "remote", "add", "origin", "git@github.com:ahmedEid1/metrics.git")
    assert repo_slug(repo) == "ahmedEid1/metrics"


def test_repo_slug_accepts_str_path(git_repo):
    """repo_slug coerces a str path (str | Path) to Path before calling git."""
    repo = git_repo["repo"]
    _run(repo, "remote", "add", "origin", "https://github.com/ahmedEid1/metrics.git")
    assert repo_slug(str(repo)) == "ahmedEid1/metrics"


def test_git_raises_on_failure_no_remote(git_repo):
    """_git uses check=True: a failing git command (no 'origin') propagates."""
    repo = git_repo["repo"]  # no remote configured
    with pytest.raises(subprocess.CalledProcessError):
        repo_slug(repo)


def test_repo_head_returns_real_head_sha(git_repo):
    """repo_head returns the actual HEAD SHA (the fix commit, not the bug)."""
    head = repo_head(git_repo["repo"])
    assert head == git_repo["fix_sha"]
    assert head != git_repo["bug_sha"]
    assert len(head) == 40  # full SHA, stripped of whitespace


# --- gather_provenance (lines 109-112) -------------------------------------


def test_gather_provenance_collects_slug_head_and_notes(git_repo):
    repo = git_repo["repo"]
    _run(repo, "remote", "add", "origin", "git@github.com:ahmedEid1/metrics.git")
    prov = gather_provenance(repo, git_repo["source_rel"], "add()")
    assert isinstance(prov, Provenance)
    assert prov.repo == "ahmedEid1/metrics"
    assert prov.base_commit == git_repo["fix_sha"]
    assert prov.source_path == git_repo["source_rel"]
    assert prov.functions == "add()"


def test_gather_provenance_missing_source_raises(git_repo):
    """The is_file() guard raises FileNotFoundError before touching git slug."""
    repo = git_repo["repo"]
    _run(repo, "remote", "add", "origin", "https://github.com/ahmedEid1/metrics.git")
    with pytest.raises(FileNotFoundError) as excinfo:
        gather_provenance(repo, "src/mypkg/does_not_exist.py", "ghost()")
    assert "does_not_exist.py" in str(excinfo.value)


# --- Provenance.as_yaml_comment (line 98) ----------------------------------


def test_as_yaml_comment_renders_all_fields():
    prov = Provenance(
        repo="ahmedEid1/metrics",
        base_commit="abc123",
        source_path="src/mypkg/metrics.py",
        functions="add()",
    )
    block = prov.as_yaml_comment()
    assert block.startswith("# Provenance\n")
    assert "#   repo:        ahmedEid1/metrics\n" in block
    assert "#   base_commit: abc123\n" in block
    assert "#   source file: src/mypkg/metrics.py\n" in block
    assert "#   functions:   add()\n" in block
    assert block.endswith("\n")
    # Every rendered line is a YAML comment (safe to prepend to meta.yaml).
    assert all(line.startswith("#") for line in block.splitlines())


# --- snapshot_source (lines 128-132) ---------------------------------------


def test_snapshot_source_copies_flat_by_basename(git_repo, tmp_path):
    """The nested source file is copied flat (bare basename) into dest_dir."""
    dest_dir = tmp_path / "base"  # does not exist yet -> mkdir branch
    dest = snapshot_source(git_repo["repo"], git_repo["source_rel"], dest_dir)
    assert dest == dest_dir / "metrics.py"
    assert dest.is_file()
    # Flat: no nested src/mypkg path under dest_dir.
    assert not (dest_dir / "src").exists()
    # Content is the HEAD (fixed) version, copied verbatim.
    assert dest.read_text() == "def add(a, b):\n    return a + b\n"


def test_snapshot_source_into_existing_dir(git_repo, tmp_path):
    """dest_dir already existing must not error (mkdir exist_ok=True)."""
    dest_dir = tmp_path / "fix"
    dest_dir.mkdir()
    (dest_dir / "preexisting.txt").write_text("keep me")
    dest = snapshot_source(git_repo["repo"], git_repo["source_rel"], dest_dir)
    assert dest.is_file()
    assert (dest_dir / "preexisting.txt").read_text() == "keep me"


# --- scaffold_task (lines 144-153) -----------------------------------------


def test_scaffold_task_creates_three_subdirs(tmp_path):
    owned_root = tmp_path / "owned"
    paths = scaffold_task("semver-002", owned_root=owned_root)
    assert paths["task"] == owned_root / "semver-002"
    for key in ("base", "test", "fix"):
        assert paths[key] == owned_root / "semver-002" / key
        assert paths[key].is_dir()
    # 'task' itself is keyed but not created as a separate mkdir target.
    assert set(paths) == {"task", "base", "test", "fix"}


def test_scaffold_task_is_idempotent(tmp_path):
    """Re-scaffolding must not wipe files already placed in the subdirs."""
    owned_root = tmp_path / "owned"
    first = scaffold_task("dup-001", owned_root=owned_root)
    (first["base"] / "metrics.py").write_text("payload")
    second = scaffold_task("dup-001", owned_root=owned_root)
    assert second["base"] == first["base"]
    assert (second["base"] / "metrics.py").read_text() == "payload"


# --- snapshot_pair (lines 163-164) -----------------------------------------


def test_snapshot_pair_writes_fix_and_base_returns_base(git_repo, tmp_path):
    owned_root = tmp_path / "owned"
    paths = scaffold_task("pair-001", owned_root=owned_root)
    returned = snapshot_pair(git_repo["repo"], git_repo["source_rel"], paths)
    base_file = paths["base"] / "metrics.py"
    fix_file = paths["fix"] / "metrics.py"
    # Both sides materialized from the same source...
    assert base_file.is_file()
    assert fix_file.is_file()
    assert base_file.read_text() == fix_file.read_text()
    # ...and snapshot_pair returns the BASE path (the one the author edits).
    assert returned == base_file


def test_module_exposes_owned_root_constant():
    """OWNED_ROOT is the default scaffold root under the repo's golden/owned."""
    assert mine_owned.OWNED_ROOT == mine_owned.REPO_ROOT / "golden" / "owned"
