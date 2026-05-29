"""Materialize a task's working tree and apply patches deterministically.

A fixture is three plain directory states under ``fixtures/<name>/``:

* ``base/`` — the repo at base_commit: BUGGY source + existing PASSING tests.
* ``test/`` — the file(s) the ``test_patch`` introduces (the failing test).
* ``fix/``  — the corrected source (the reference / "gold" solution).

Unified diffs (``test_patch``, ``gold_patch``) are *derived* from these states
with git, so authors never hand-write diffs. Patch application also goes through
git (``git apply``, with a 3-way fallback), mirroring the SWE-bench harness.
"""

import contextlib
import os
import shutil
import signal
import subprocess
import sys
import tempfile
from pathlib import Path
from xml.etree import ElementTree

# Default per-node pytest wall-clock budget (seconds). A candidate patch is
# applied to the source the oracle imports, so a patch with `while True: pass`,
# unbounded recursion, a deadlock, or catastrophic-backtracking regex would
# otherwise hang the grader forever. A timed-out node is recorded as NOT passed.
NODE_TIMEOUT_DEFAULT = 120.0

# swebench TestStatus string values (kept literal so the swebench extra stays
# optional). A node is a "pass" for resolution purposes only when its status is
# PASSED or XFAIL — mirroring swebench's grading.test_passed.
_STATUS_PASSED = "PASSED"
_STATUS_FAILED = "FAILED"
_STATUS_ERROR = "ERROR"
_STATUS_SKIPPED = "SKIPPED"
_STATUS_XFAIL = "XFAIL"
_PASSING_STATUSES = frozenset({_STATUS_PASSED, _STATUS_XFAIL})

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
    """Stage all changes and return the unified diff vs the base commit.

    ``--renormalize`` forces git to re-hash tracked files instead of trusting its
    ``(mtime, size)`` stat cache. Without it, an edit that preserves a file's byte
    size (e.g. swapping ``a, b`` -> ``b, a``) on a copy that kept the original
    mtime is silently treated as unchanged, yielding an empty (wrong) diff.
    """
    git(workdir, "add", "-A")
    git(workdir, "add", "--renormalize", "-A")
    return git(workdir, "diff", "--cached", "--no-color").stdout


def reset_to_base(workdir: str | Path) -> None:
    """Discard all changes (tracked + untracked) back to the base commit."""
    git(workdir, "reset", "-q", "--hard", "HEAD")
    git(workdir, "clean", "-qfd")


def _parse_junit_statuses(xml_text: str) -> dict[str, str]:
    """Map ``classname.name`` -> swebench TestStatus string from a junit-xml report.

    pytest's junit-xml is machine-readable per test case:

    * no child element                          -> PASSED   (also non-strict xpass)
    * ``<failure>``                             -> FAILED   (incl. strict XPASS)
    * ``<error>``                               -> ERROR
    * ``<skipped type="pytest.xfail">``         -> XFAIL
    * ``<skipped …>`` (any other skip)          -> SKIPPED

    This is the source-of-truth pytest *result* — never its process exit code,
    which is 0 for a SKIPPED test and would falsely read as a pass.
    """
    statuses: dict[str, str] = {}
    if not xml_text.strip():
        return statuses
    # The XML is emitted by our own pinned pytest subprocess. Defend against XXE /
    # billion-laughs anyway: both require a DOCTYPE/DTD or custom entity, which
    # pytest never emits, so reject any report that contains one before parsing.
    if "<!DOCTYPE" in xml_text or "<!ENTITY" in xml_text:
        return statuses
    try:
        root = ElementTree.fromstring(xml_text)
    except ElementTree.ParseError:
        return statuses
    for case in root.iter("testcase"):
        classname = case.get("classname") or ""
        name = case.get("name") or ""
        key = f"{classname}.{name}" if classname else name
        if case.find("error") is not None:
            status = _STATUS_ERROR
        elif case.find("failure") is not None:
            status = _STATUS_FAILED
        else:
            skipped = case.find("skipped")
            if skipped is not None:
                status = _STATUS_XFAIL if skipped.get("type") == "pytest.xfail" else _STATUS_SKIPPED
            else:
                status = _STATUS_PASSED
        statuses[key] = status
    return statuses


def _status_for_nodeid(nodeid: str, parsed: dict[str, str]) -> str:
    """Resolve one ``file.py::Class::test[param]`` node id to its junit status.

    Junit keys a case by ``classname.name`` where classname is the dotted
    module/class path and name is the (possibly parametrized) function. We match
    on the trailing function segment(s) so a bare node id and its key line up,
    and treat 'never appeared' (deselected / 'no tests ran') as FAILED.
    """
    if not parsed:
        return _STATUS_FAILED
    func = nodeid.split("::", 1)[1] if "::" in nodeid else nodeid
    func = func.replace("::", ".")
    for key, status in parsed.items():
        if key == func or key.endswith("." + func):
            return status
    return _STATUS_FAILED


def _run_pytest(
    cmd: list[str], workdir: str | Path, env: dict[str, str], timeout: float | None
) -> tuple[int, str, bool]:
    """Run ``cmd`` capturing stdout; enforce ``timeout`` by killing the whole
    process group. Returns ``(returncode, stdout, timed_out)``.

    The child runs in its own session (``start_new_session``) so a timeout can
    ``killpg`` the entire group — reliably reaping any subprocesses a candidate
    patch or pytest itself spawned (a single ``proc.kill()`` would orphan them).
    """
    proc = subprocess.Popen(
        cmd,
        cwd=str(workdir),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        env=env,
        start_new_session=True,
    )
    try:
        out, _ = proc.communicate(timeout=timeout)
        return proc.returncode, out or "", False
    except subprocess.TimeoutExpired:
        _killpg(proc)
        try:
            out, _ = proc.communicate(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
            out, _ = proc.communicate()
        return proc.returncode if proc.returncode is not None else -1, out or "", True


def _killpg(proc: "subprocess.Popen") -> None:
    """SIGKILL the process group led by ``proc`` (best effort)."""
    try:
        os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
    except OSError:  # ProcessLookupError / PermissionError both subclass OSError
        with contextlib.suppress(OSError):
            proc.kill()


def run_nodeids_status_map(
    workdir: str | Path,
    nodeids: list[str],
    *,
    python: str | None = None,
    timeout: float | None = NODE_TIMEOUT_DEFAULT,
) -> tuple[dict[str, str], str]:
    """Run each pytest node id; return ``({nodeid: swebench-status}, logs)``.

    The status is parsed from a per-node junit-xml report, so it is pytest's
    *real* outcome (PASSED/FAILED/ERROR/SKIPPED/XFAIL) rather than the process
    exit code. A node that hits ``timeout`` (default :data:`NODE_TIMEOUT_DEFAULT`
    seconds) is recorded as FAILED with a ``[timeout]`` note.

    ``-B`` / PYTHONDONTWRITEBYTECODE: never write .pyc. Critical for correctness —
    when a source file is patched in place and the edit preserves its byte size
    within the same wall-clock second, CPython's (mtime, size) .pyc cache would
    otherwise serve STALE bytecode for the newly-patched file.
    """
    python = python or sys.executable
    env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
    status: dict[str, str] = {}
    logs: list[str] = []
    for nodeid in nodeids:
        with tempfile.NamedTemporaryFile("w", suffix=".xml", delete=False) as fh:
            xml_path = fh.name
        try:
            cmd = [
                python, "-B", "-m", "pytest", nodeid,
                "-q", "--no-header", "-p", "no:cacheprovider",
                "-o", "junit_family=xunit2", "--junit-xml", xml_path,
            ]
            rc, out, timed_out = _run_pytest(cmd, workdir, env, timeout)
            if timed_out:
                status[nodeid] = _STATUS_FAILED
                logs.append(f"$ pytest {nodeid} -> [timeout after {timeout}s] (FAIL)")
                logs.append(out[-2000:])
                continue
            try:
                xml_text = Path(xml_path).read_text()
            except OSError:
                xml_text = ""
        finally:
            Path(xml_path).unlink(missing_ok=True)
        parsed = _parse_junit_statuses(xml_text)
        node_status = _status_for_nodeid(nodeid, parsed)
        status[nodeid] = node_status
        logs.append(f"$ pytest {nodeid} -> rc={rc} status={node_status}")
        logs.append(out[-2000:])
    return status, "\n".join(logs)


def run_nodeids_status(
    workdir: str | Path,
    nodeids: list[str],
    *,
    python: str | None = None,
    timeout: float | None = NODE_TIMEOUT_DEFAULT,
) -> tuple[dict[str, bool], str]:
    """Run each pytest node id in its own process; return ``({nodeid: passed}, logs)``.

    A node is ``True`` (passed) ONLY when pytest reports it as PASSED or XFAIL
    (the swebench ``test_passed`` rule); SKIPPED/DESELECTED/'no tests ran'/timeout
    are ``False``. Pass/fail is read from a machine-readable junit report, never
    from the process exit code (which is 0 for a SKIPPED test — see
    :func:`run_nodeids_status_map`).

    Behaviour for ordinary passes and failures is unchanged.
    """
    statuses, logs = run_nodeids_status_map(workdir, nodeids, python=python, timeout=timeout)
    status = {nodeid: (s in _PASSING_STATUSES) for nodeid, s in statuses.items()}
    return status, logs


def run_nodeids(
    workdir: str | Path, nodeids: list[str], *, python: str | None = None
) -> tuple[int, int, str]:
    """Run each pytest node id and count how many pass: ``(passed, total, logs)``."""
    status, logs = run_nodeids_status(workdir, nodeids, python=python)
    return sum(status.values()), len(nodeids), logs
