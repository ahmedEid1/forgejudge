"""Regression coverage for the junit-xml parsing + per-node timeout branches in
``forgejudge.golden.materialize`` (added in WF2).

These tests exercise the result-grading rules directly:

* a TIMED-OUT node must be recorded NOT-passed (never trusting the exit code);
* a SKIPPED / DESELECTED / errored-at-collection node must be NOT-passed;
* xfail -> pass, strict xpass (emitted as ``<failure>``) -> not-pass;
* malformed / hostile (DOCTYPE/ENTITY) junit reports degrade to "no statuses".

The end-to-end cases use tiny synthetic test files in ``tmp_path`` and a tiny
timeout (1s budget vs a 30s sleep) so the suite stays fast and hermetic — no
real LLM/provider calls, no DB, no network.
"""

import subprocess
import sys
from pathlib import Path

import pytest

from forgejudge.golden import materialize as M

# --------------------------------------------------------------------------- #
# _parse_junit_statuses: empty / hostile / malformed inputs (lines 130,135,138-139)
# --------------------------------------------------------------------------- #


def test_parse_junit_empty_text_returns_empty_map():
    """An empty (or whitespace-only) report yields no statuses, not a crash."""
    assert M._parse_junit_statuses("") == {}
    assert M._parse_junit_statuses("   \n\t ") == {}


def test_parse_junit_rejects_doctype():
    """A report carrying a DOCTYPE is rejected wholesale (XXE/billion-laughs guard)."""
    xml = (
        '<!DOCTYPE testsuites>'
        '<testsuites><testsuite><testcase classname="m" name="t"/></testsuite></testsuites>'
    )
    assert M._parse_junit_statuses(xml) == {}


def test_parse_junit_rejects_entity_declaration():
    """A custom ENTITY declaration is likewise rejected before parsing."""
    xml = (
        '<!ENTITY lol "lol">'
        '<testsuites><testsuite><testcase classname="m" name="t"/></testsuite></testsuites>'
    )
    assert M._parse_junit_statuses(xml) == {}


def test_parse_junit_malformed_xml_returns_empty_map():
    """Unparseable XML degrades to an empty map (ParseError swallowed)."""
    assert M._parse_junit_statuses("<testsuite><testcase></notclosed>") == {}


# --------------------------------------------------------------------------- #
# _parse_junit_statuses: per-case status mapping (lines 145, 151, and the rest)
# --------------------------------------------------------------------------- #


def test_parse_junit_maps_each_outcome_to_status():
    """error -> ERROR, failure -> FAILED, xfail-skip -> XFAIL, plain skip -> SKIPPED,
    no child -> PASSED. Covers both branches of the skipped sub-decision."""
    xml = """<testsuites><testsuite>
      <testcase classname="m.test_mod" name="test_pass"/>
      <testcase classname="m.test_mod" name="test_fail"><failure>boom</failure></testcase>
      <testcase classname="m.test_mod" name="test_err"><error>collect</error></testcase>
      <testcase classname="m.test_mod" name="test_xfail">
        <skipped type="pytest.xfail">expected</skipped>
      </testcase>
      <testcase classname="m.test_mod" name="test_skip">
        <skipped type="pytest.skip">nope</skipped>
      </testcase>
    </testsuite></testsuites>"""
    parsed = M._parse_junit_statuses(xml)
    assert parsed["m.test_mod.test_pass"] == M._STATUS_PASSED
    assert parsed["m.test_mod.test_fail"] == M._STATUS_FAILED
    assert parsed["m.test_mod.test_err"] == M._STATUS_ERROR
    assert parsed["m.test_mod.test_xfail"] == M._STATUS_XFAIL
    assert parsed["m.test_mod.test_skip"] == M._STATUS_SKIPPED


def test_parse_junit_error_wins_over_failure():
    """A case that is both errored and failed is classified ERROR (error checked first)."""
    xml = (
        '<testsuites><testsuite><testcase classname="m" name="t">'
        "<error>e</error><failure>f</failure>"
        "</testcase></testsuite></testsuites>"
    )
    assert M._parse_junit_statuses(xml) == {"m.t": M._STATUS_ERROR}


def test_parse_junit_blank_classname_keys_on_name_only():
    """With no classname the key is the bare name (the `if classname else name` arm)."""
    xml = '<testsuites><testsuite><testcase name="test_lonely"/></testsuite></testsuites>'
    assert M._parse_junit_statuses(xml) == {"test_lonely": M._STATUS_PASSED}


# --------------------------------------------------------------------------- #
# _status_for_nodeid: lookup / fallback (lines 167, 173)
# --------------------------------------------------------------------------- #


def test_status_for_nodeid_empty_parsed_is_failed():
    """No parsed cases at all (e.g. 'no tests ran' / deselected) -> FAILED."""
    assert M._status_for_nodeid("test_x.py::test_a", {}) == M._STATUS_FAILED


def test_status_for_nodeid_not_found_is_failed():
    """A node id absent from the report (deselected) -> FAILED, not silently passed."""
    parsed = {"pkg.test_x.test_other": M._STATUS_PASSED}
    assert M._status_for_nodeid("test_x.py::test_a", parsed) == M._STATUS_FAILED


def test_status_for_nodeid_matches_trailing_function_segment():
    """A bare node id lines up with the dotted classname.name key via suffix match."""
    parsed = {"pkg.test_x.TestC.test_a": M._STATUS_XFAIL}
    assert M._status_for_nodeid("test_x.py::TestC::test_a", parsed) == M._STATUS_XFAIL


def test_status_for_nodeid_exact_key_match():
    """When the func segment equals a key exactly, that status is returned."""
    parsed = {"test_a": M._STATUS_PASSED}
    assert M._status_for_nodeid("test_a", parsed) == M._STATUS_PASSED


# --------------------------------------------------------------------------- #
# _killpg: success path + OSError fallback (lines 210-214)
# --------------------------------------------------------------------------- #


def test_killpg_kills_process_group():
    """_killpg(real-proc) terminates a live child via its process group."""
    proc = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(30)"],
        start_new_session=True,
    )
    M._killpg(proc)
    proc.wait(timeout=10)
    assert proc.returncode is not None  # was reaped, not left running


def test_killpg_oserror_falls_back_to_proc_kill(monkeypatch):
    """If os.killpg raises OSError (e.g. group already gone), _killpg falls back to
    proc.kill() — covering the except branch (lines 212-214)."""

    def boom(*_a, **_k):
        raise ProcessLookupError("no such group")

    monkeypatch.setattr(M.os, "killpg", boom)

    killed = {"n": 0}

    class FakeProc:
        pid = 4242

        def kill(self):
            killed["n"] += 1

    M._killpg(FakeProc())
    assert killed["n"] == 1, "fallback proc.kill() must run when killpg raises"


# --------------------------------------------------------------------------- #
# _run_pytest: timeout path (lines 198-205)
# --------------------------------------------------------------------------- #


def test_run_pytest_timeout_kills_and_flags(tmp_path):
    """A command that sleeps past the timeout is killed and reported timed_out=True.

    Drives the TimeoutExpired branch: communicate(timeout) raises, _killpg reaps
    the group, and the second communicate() returns. Budget 1s vs a 30s sleep."""
    cmd = [sys.executable, "-c", "import time; time.sleep(30)"]
    rc, out, timed_out = M._run_pytest(cmd, tmp_path, {**M.os.environ}, timeout=1.0)
    assert timed_out is True
    assert isinstance(out, str)
    assert rc != 0 or rc == -1  # killed process never exits 0 cleanly


def test_run_pytest_timeout_then_hard_kill(tmp_path, monkeypatch):
    """If the process is still wedged after killpg (first reap also times out),
    _run_pytest escalates to proc.kill() and a final communicate (lines 202-204).

    We fake Popen so the first communicate() raises TimeoutExpired (triggers
    killpg), the second communicate(timeout=10) ALSO raises TimeoutExpired
    (triggers proc.kill()), and the third returns output."""
    calls = {"communicate": 0, "kill": 0}

    class FakeProc:
        pid = 9999
        returncode = None

        def communicate(self, timeout=None):
            calls["communicate"] += 1
            if calls["communicate"] == 1:
                raise subprocess.TimeoutExpired(cmd="x", timeout=timeout)
            if calls["communicate"] == 2:
                raise subprocess.TimeoutExpired(cmd="x", timeout=timeout)
            return ("late output", "")

        def kill(self):
            calls["kill"] += 1

    monkeypatch.setattr(M.subprocess, "Popen", lambda *a, **k: FakeProc())
    monkeypatch.setattr(M, "_killpg", lambda proc: None)

    rc, out, timed_out = M._run_pytest(["x"], tmp_path, {}, timeout=0.01)
    assert timed_out is True
    assert calls["kill"] == 1, "hard proc.kill() must fire when the reap also times out"
    assert calls["communicate"] == 3
    assert out == "late output"
    assert rc == -1  # returncode stayed None -> reported as -1


def test_run_pytest_normal_completion_not_timed_out(tmp_path):
    """The happy path: a fast command completes, timed_out=False, output captured."""
    cmd = [sys.executable, "-c", "print('hello-from-child')"]
    rc, out, timed_out = M._run_pytest(cmd, tmp_path, {**M.os.environ}, timeout=30.0)
    assert timed_out is False
    assert rc == 0
    assert "hello-from-child" in out


# --------------------------------------------------------------------------- #
# run_nodeids_status[_map]: end-to-end timeout + skip + collection error
# (lines 251-254 for timeout, plus the SKIPPED/ERROR grading rules)
# --------------------------------------------------------------------------- #


def _write(p: Path, body: str) -> None:
    p.write_text(body)


def test_timed_out_node_is_not_passed(tmp_path):
    """A node that sleeps past a tiny per-node budget is recorded NOT-passed and
    annotated [timeout] in the logs (lines 251-254)."""
    _write(
        tmp_path / "test_slow.py",
        "import time\n\n\ndef test_hang():\n    time.sleep(30)\n",
    )
    status, logs = M.run_nodeids_status(
        tmp_path, ["test_slow.py::test_hang"], timeout=1.0
    )
    assert status == {"test_slow.py::test_hang": False}
    assert "[timeout after 1.0s] (FAIL)" in logs

    # And the status-map variant records the raw swebench FAILED status.
    smap, _ = M.run_nodeids_status_map(
        tmp_path, ["test_slow.py::test_hang"], timeout=1.0
    )
    assert smap["test_slow.py::test_hang"] == M._STATUS_FAILED


def test_skipped_node_is_not_passed(tmp_path):
    """A SKIPPED test exits pytest with rc=0 but must NOT count as a pass."""
    _write(
        tmp_path / "test_skip.py",
        "import pytest\n\n\n@pytest.mark.skip(reason='nope')\n"
        "def test_skipped():\n    assert True\n",
    )
    status, _ = M.run_nodeids_status(tmp_path, ["test_skip.py::test_skipped"])
    assert status == {"test_skip.py::test_skipped": False}

    smap, _ = M.run_nodeids_status_map(tmp_path, ["test_skip.py::test_skipped"])
    assert smap["test_skip.py::test_skipped"] == M._STATUS_SKIPPED


def test_collection_error_node_is_not_passed(tmp_path):
    """A node that errors at collection (import-time failure) is NOT a pass."""
    _write(
        tmp_path / "test_broken.py",
        "import this_module_does_not_exist  # noqa\n\n\ndef test_x():\n    assert True\n",
    )
    status, _ = M.run_nodeids_status(tmp_path, ["test_broken.py::test_x"])
    assert status == {"test_broken.py::test_x": False}


def test_xfail_passes_and_xpass_strict_fails(tmp_path):
    """xfail -> pass (XFAIL in _PASSING_STATUSES); strict xpass -> NOT pass
    (pytest emits it as <failure>, graded FAILED)."""
    _write(
        tmp_path / "test_xf.py",
        "import pytest\n\n\n"
        "@pytest.mark.xfail(reason='known bug')\n"
        "def test_xfail():\n    assert False\n\n\n"
        "@pytest.mark.xfail(strict=True, reason='should fail')\n"
        "def test_xpass_strict():\n    assert True\n",
    )
    status, _ = M.run_nodeids_status(
        tmp_path,
        ["test_xf.py::test_xfail", "test_xf.py::test_xpass_strict"],
    )
    assert status["test_xf.py::test_xfail"] is True
    assert status["test_xf.py::test_xpass_strict"] is False


def test_ordinary_pass_and_fail(tmp_path):
    """Sanity: a genuine pass is True, a genuine failure is False — the unchanged
    happy path also drives the xml read + parse + nodeid-resolve flow."""
    _write(
        tmp_path / "test_pf.py",
        "def test_ok():\n    assert 1 + 1 == 2\n\n\ndef test_bad():\n    assert 1 == 2\n",
    )
    status, logs = M.run_nodeids_status(
        tmp_path, ["test_pf.py::test_ok", "test_pf.py::test_bad"]
    )
    assert status["test_pf.py::test_ok"] is True
    assert status["test_pf.py::test_bad"] is False
    assert "status=PASSED" in logs and "status=FAILED" in logs


def test_run_nodeids_counts_passes(tmp_path):
    """run_nodeids aggregates the per-node map into (passed, total)."""
    _write(
        tmp_path / "test_cnt.py",
        "def test_a():\n    assert True\n\n\ndef test_b():\n    assert False\n",
    )
    passed, total, _ = M.run_nodeids(
        tmp_path, ["test_cnt.py::test_a", "test_cnt.py::test_b"]
    )
    assert (passed, total) == (1, 2)


def test_unreadable_xml_falls_back_to_failed(tmp_path, monkeypatch):
    """If the junit report can't be read (OSError), xml_text becomes '' and the
    node resolves to FAILED (covers lines 257-258 + the empty-parse fallback)."""
    _write(tmp_path / "test_r.py", "def test_a():\n    assert True\n")

    real_read_text = Path.read_text

    def fake_read_text(self, *a, **k):
        if self.suffix == ".xml":
            raise OSError("simulated unreadable junit report")
        return real_read_text(self, *a, **k)

    monkeypatch.setattr(Path, "read_text", fake_read_text)

    status, _ = M.run_nodeids_status(tmp_path, ["test_r.py::test_a"])
    # Even though the test really passes, an unreadable report => empty parse => FAILED.
    assert status == {"test_r.py::test_a": False}


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
