"""Mutation-based weak-test detection.

A golden task is only credible if its tests would catch a *wrong* fix. We mutate
the gold-fixed source and require the FAIL_TO_PASS/PASS_TO_PASS suite to kill the
mutants. A task whose tests pass under deliberately-wrong code must be flagged.
"""

from pathlib import Path

import pytest
import yaml

from forgejudge.golden.build_dataset import build_task
from forgejudge.golden.harden import generate_mutants, harden_check

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SEMVER_DIR = REPO_ROOT / "forgejudge" / "golden" / "fixtures" / "semver-001"


def test_generate_mutants_produces_variants():
    src = "def f(a, b):\n    if a < b:\n        return a + b\n    return 0\n"
    mutants = generate_mutants(src)
    assert len(mutants) >= 2
    assert all(m != src for _, m in mutants)


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
