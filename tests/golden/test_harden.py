"""Mutation-based weak-test detection.

A golden task is only credible if its tests would catch a *wrong* fix. We mutate
the gold-fixed source and require the FAIL_TO_PASS/PASS_TO_PASS suite to kill the
mutants. A task whose tests pass under deliberately-wrong code must be flagged.
"""

from pathlib import Path

import pytest
import yaml

from forgejudge.golden.build_dataset import build_task
from forgejudge.golden.harden import (
    changed_line_numbers,
    generate_mutants,
    harden_check,
)

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SEMVER_DIR = REPO_ROOT / "forgejudge" / "golden" / "fixtures" / "semver-001"
JSONPATH_DIR = REPO_ROOT / "forgejudge" / "golden" / "fixtures" / "jsonpath-001"


def test_generate_mutants_produces_variants():
    src = "def f(a, b):\n    if a < b:\n        return a + b\n    return 0\n"
    mutants = generate_mutants(src)
    assert len(mutants) >= 2
    assert all(m != src for _, m in mutants)


def test_deletion_only_fix_returns_none_scope():
    """Finding #5: a pure-deletion gold fix changes the file but yields no added
    lines. changed_line_numbers must signal 'mutate the whole file' (None), not an
    empty set (which would silently scope out every node -> zero mutants)."""
    base = "x = 1\ny = 2\nz = 3\n"
    fix = "x = 1\nz = 3\n"  # the `y = 2` line was deleted
    scope = changed_line_numbers(base, fix)
    assert scope is None, (
        "a deletion that changes the file must not yield an empty scope "
        f"(got {scope!r}), or mutation probes nothing"
    )
    # And the deletion-scoped file still produces mutable nodes.
    assert generate_mutants(fix, scope), "whole-file fallback must find mutants"


def test_jsonpath_deletion_fixture_is_not_inconclusive():
    """Finding #5 end-to-end: jsonpath-001's gold fix is a pure deletion. With the
    bug, its surviving comparisons are never mutation-probed and the task is
    wrongly reported 'inconclusive'. The whole-file fallback must generate mutants."""
    base = (JSONPATH_DIR / "base" / "jsonpath.py").read_text()
    fix = (JSONPATH_DIR / "fix" / "jsonpath.py").read_text()
    assert base != fix
    scope = changed_line_numbers(base, fix)
    assert scope is None
    assert generate_mutants(fix, scope), (
        "deletion-only fix must still yield mutants over the surviving logic"
    )


def test_multiline_node_scoped_by_continuation_line():
    """Finding #21: _in_scope must use the node's full line span, so an operator
    reported on a continuation line (not the node's start line) is still mutated."""
    src = "x = (\n    a\n    < b\n)\n"  # Compare lineno=2, end_lineno=3
    # The `<` operator sits on line 3 (a continuation line); the gold diff may
    # report only that line as changed.
    assert generate_mutants(src, {3}), (
        "a node whose changed line is a continuation line must still be mutated"
    )
    # Sanity: start-line scoping already worked.
    assert generate_mutants(src, {2})


@pytest.mark.slow
def test_strong_fixture_survives_hardening():
    task, gold = build_task(SEMVER_DIR)
    result = harden_check(task, SEMVER_DIR)
    assert result.mutants_total > 0
    assert result.mutants_killed > 0
    assert result.mutation_score >= 0.5
    assert result.passed, f"strong fixture should pass hardening; survivors={result.survivors}"


def _write_weak_task(root: Path) -> Path:
    """A task whose tests only check the *type* of the result — too weak to catch
    any wrong arithmetic. Mutants must survive."""
    d = root / "weak-001"
    (d / "base").mkdir(parents=True)
    (d / "test").mkdir(parents=True)
    (d / "fix").mkdir(parents=True)
    (d / "base" / "calc.py").write_text("def add(a, b):\n    return a - b\n")          # buggy
    (d / "fix" / "calc.py").write_text("def add(a, b):\n    return a + b\n")           # correct
    (d / "base" / "test_calc.py").write_text(
        "from calc import add\n\n\ndef test_type():\n    assert isinstance(add(2, 2), int)\n"
    )
    (d / "test" / "test_calc_bug.py").write_text(
        "from calc import add\n\n\ndef test_type2():\n    assert isinstance(add(5, 5), int)\n"
    )
    (d / "meta.yaml").write_text(
        yaml.safe_dump(
            {
                "instance_id": "weak-001",
                "family": "make_ci_green",
                "problem_statement": "add() is wrong.",
                "source_license": "own",
                "created_at": "2026-05-29",
                "env_image": "python:3.12-slim",
                "fail_to_pass": ["test_calc_bug.py::test_type2"],
                "pass_to_pass": ["test_calc.py::test_type"],
            }
        )
    )
    return d


@pytest.mark.slow
def test_no_golden_task_is_mutation_weak():
    """Credibility invariant: no task in the golden set may have weak tests.

    'inconclusive' (no AST-mutable nodes in the patched region — e.g. regex /
    string / call-order code) is allowed; such tasks are still intrinsically
    verified. Only 'weak' (mutants generated and survived) is forbidden.
    """
    from forgejudge.golden.build_dataset import discover_task_dirs

    weak = []
    for d in discover_task_dirs():
        task, _ = build_task(d)
        r = harden_check(task, d)
        if r.status == "weak":
            weak.append((task.instance_id, r.mutation_score, r.survivors))
    assert not weak, f"weak (under-tested) golden tasks: {weak}"


@pytest.mark.slow
def test_weak_tests_are_flagged(tmp_path):
    d = _write_weak_task(tmp_path)
    task, _gold = build_task(d)
    result = harden_check(task, d)
    assert result.mutants_total > 0
    assert result.survivors, "weak tests should let mutants survive"
    assert result.mutation_score == 0.0
    assert not result.passed
