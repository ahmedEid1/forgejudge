"""The CI regression gate (spec decision #12): only a statistically real,
CI-separated drop in per-seed resolution rate should block a change. Identical,
overlapping, flaky-but-overlapping, and improved runs must all pass.
"""

import json
import math

import pytest

from forgejudge.eval.gate import (
    GateResult,
    exact_gold_gate,
    mean_ci,
    regression_gate,
    resolution_rate_from_run_artifacts,
    scores_from_run_artifacts,
)


def test_identical_distributions_pass():
    res = regression_gate([0.6, 0.6, 0.6], [0.6, 0.6, 0.6])
    assert isinstance(res, GateResult)
    assert res.passed is True


def test_overlapping_noisy_distributions_pass():
    res = regression_gate([0.6, 0.55, 0.65], [0.58, 0.5, 0.62])
    assert res.passed is True


def test_clear_separated_regression_fails():
    res = regression_gate([0.8, 0.82, 0.81, 0.79], [0.4, 0.42, 0.38, 0.41])
    assert res.passed is False
    # detail must explain the decision with the bound numbers.
    assert f"{res.candidate_upper:.4f}" in res.detail
    assert f"{res.baseline_lower:.4f}" in res.detail
    assert res.candidate_upper < res.baseline_lower


def test_single_flaky_low_seed_does_not_fail():
    # One bad seed widens the candidate CI so much it still overlaps baseline.
    res = regression_gate([0.7, 0.7, 0.7, 0.7], [0.7, 0.7, 0.7, 0.3])
    assert res.passed is True


def test_improvement_passes():
    res = regression_gate([0.5, 0.5], [0.9, 0.9])
    assert res.passed is True


def test_mean_ci_ordering():
    mean, lower, upper = mean_ci([0.4, 0.6, 0.5, 0.55])
    assert lower <= mean <= upper
    assert math.isclose(mean, 0.5125)


def test_mean_ci_single_sample_is_degenerate():
    mean, lower, upper = mean_ci([0.42])
    assert lower == mean == upper == 0.42


def test_mean_ci_empty_is_zero():
    assert mean_ci([]) == (0.0, 0.0, 0.0)


def test_both_empty_raises():
    with pytest.raises(ValueError):
        regression_gate([], [])


def test_one_empty_side_is_tolerated():
    # Candidate produced nothing -> mean 0.0; baseline solidly above -> fail.
    res = regression_gate([0.9, 0.9, 0.9], [])
    assert res.passed is False
    # Empty baseline (mean 0.0) cannot be regressed against -> pass.
    res2 = regression_gate([], [0.9, 0.9, 0.9])
    assert res2.passed is True


# --- Finding #17: small-n CI must use Student-t, not the fixed z=1.96 ----------


def test_mean_ci_small_n_uses_student_t_not_normal_z():
    """For n=3 the half-width must use t_{.975,2}=4.303, not z=1.96.

    With the buggy fixed-z, the half-width is ~2.2x too narrow. Pin the wider,
    statistically-correct interval so the gate is not over-eager to FAIL.
    """
    scores = [0.5, 0.6, 0.7]
    mean, lower, upper = mean_ci(scores)
    stderr = math.sqrt(sum((s - 0.6) ** 2 for s in scores) / 2) / math.sqrt(3)
    t_crit = 4.302653  # t_{.975, dof=2}
    expected_half = t_crit * stderr
    assert math.isclose(mean, 0.6, abs_tol=1e-9)
    assert math.isclose(upper - mean, expected_half, rel_tol=1e-3), (
        f"half-width {upper - mean} should match Student-t {expected_half}"
    )
    # The normal-z half-width would be much narrower; reject it.
    z_half = 1.96 * stderr
    assert (upper - mean) > z_half * 1.5


def test_mean_ci_widening_prevents_over_eager_fail_at_n3():
    """A non-regressed candidate with ordinary seed noise must not FAIL.

    Under the buggy fixed-z this exact case crosses the threshold and fails;
    with Student-t the intervals overlap and it passes.
    """
    baseline = [0.80, 0.82, 0.78]
    candidate = [0.71, 0.73, 0.69]
    # Sanity: under the buggy fixed z=1.96 this separates and FAILS.
    import statistics

    def _z_fails(b, c, z=1.96):
        bl = statistics.mean(b) - z * statistics.stdev(b) / math.sqrt(len(b))
        cu = statistics.mean(c) + z * statistics.stdev(c) / math.sqrt(len(c))
        return cu < bl

    assert _z_fails(baseline, candidate) is True
    # With the correct Student-t multiplier the intervals overlap -> PASS.
    res = regression_gate(baseline, candidate)
    assert res.passed is True


# --- Finding #18: single-seed / single-point baseline is statistically unsound -


def test_single_seed_baseline_is_rejected_as_insufficient():
    """A single-point baseline has no variance estimate; the gate must not

    silently render a verdict from it. It should refuse (raise / not-passed),
    never quietly PASS a candidate it cannot judge.
    """
    with pytest.raises(ValueError):
        regression_gate([1.0], [1.0, 1.0, 1.0])


def test_single_seed_candidate_is_rejected_as_insufficient():
    with pytest.raises(ValueError):
        regression_gate([0.8, 0.82, 0.79], [1.0])


def test_committed_baseline_scores_json_is_multi_seed(tmp_path):
    """The shipped baseline must be a real >=3-seed sample, not [1.0]."""
    from pathlib import Path

    repo_root = Path(__file__).resolve().parent.parent.parent
    baseline = json.loads((repo_root / "eval" / "baseline_scores.json").read_text())
    assert isinstance(baseline, list)
    assert len(baseline) >= 3, "baseline must carry >=3 per-seed scores"
    assert all(isinstance(x, (int, float)) and 0.0 <= x <= 1.0 for x in baseline)
    # Must be usable by the gate without tripping the insufficient-seed guard.
    res = regression_gate(baseline, [0.9, 0.9, 0.9])
    assert isinstance(res, GateResult)


# --- Findings #2 / #4: deterministic gold gate must require exact correctness --


def _write_shard(dirpath, name, resolved_flags):
    recs = [{"task_id": f"t{i}", "resolved": bool(r)} for i, r in enumerate(resolved_flags)]
    (dirpath / name).write_text("".join(json.dumps(r) + "\n" for r in recs))


def test_resolution_rate_pools_all_shards_into_one_rate(tmp_path):
    """The gold gate must aggregate ALL shard records into ONE rate, not treat

    each shard as an independent seed.
    """
    d = tmp_path / "artifacts"
    d.mkdir()
    # 12 gold tasks across 4 shards of 3; one task in shard 2 fails.
    _write_shard(d, "runs-shard-0.jsonl", [1, 1, 1])
    _write_shard(d, "runs-shard-1.jsonl", [1, 1, 1])
    _write_shard(d, "runs-shard-2.jsonl", [1, 1, 0])
    _write_shard(d, "runs-shard-3.jsonl", [1, 1, 1])
    rate, resolved, total = resolution_rate_from_run_artifacts(d)
    assert math.isclose(rate, 11 / 12)
    assert (resolved, total) == (11, 12)


def test_exact_gold_gate_fails_on_single_unresolved_task(tmp_path):
    """A partial harness breakage (1 of 12 gold tasks) MUST fail the gate.

    This is the exact scenario the CI-overlap gate silently passed.
    """
    d = tmp_path / "artifacts"
    d.mkdir()
    _write_shard(d, "runs-shard-0.jsonl", [1, 1, 1])
    _write_shard(d, "runs-shard-1.jsonl", [1, 1, 1])
    _write_shard(d, "runs-shard-2.jsonl", [1, 1, 0])
    _write_shard(d, "runs-shard-3.jsonl", [1, 1, 1])
    res = exact_gold_gate(d)
    assert res.passed is False
    assert "11" in res.detail or "0.9" in res.detail


def test_exact_gold_gate_passes_only_when_all_resolve(tmp_path):
    d = tmp_path / "artifacts"
    d.mkdir()
    _write_shard(d, "runs-shard-0.jsonl", [1, 1, 1])
    _write_shard(d, "runs-shard-1.jsonl", [1, 1, 1])
    _write_shard(d, "runs-shard-2.jsonl", [1, 1, 1])
    _write_shard(d, "runs-shard-3.jsonl", [1, 1, 1])
    res = exact_gold_gate(d)
    assert res.passed is True


def test_exact_gold_gate_fails_on_empty_artifacts(tmp_path):
    d = tmp_path / "artifacts"
    d.mkdir()
    res = exact_gold_gate(d)
    assert res.passed is False


def test_scores_from_run_artifacts_still_lists_per_file_rates(tmp_path):
    """Back-compat: the per-file helper still returns one rate per jsonl."""
    d = tmp_path / "artifacts"
    d.mkdir()
    _write_shard(d, "a.jsonl", [1, 1, 1])
    _write_shard(d, "b.jsonl", [1, 1, 0])
    scores = scores_from_run_artifacts(d)
    assert scores == [1.0, 2 / 3]


# === APPENDED COVERAGE TESTS (gate.py lines 75, 216, 264-302, 306) ============
#
# Targets: the _t_critical normal-approx fallback, the blank-line skip in
# resolution_rate_from_run_artifacts, the artifact-driven scores_from_run_
# artifacts loader against blank/empty files, and every branch of main().

import runpy  # noqa: E402
import statistics  # noqa: E402
import sys  # noqa: E402
import warnings  # noqa: E402

from forgejudge.eval.gate import _t_critical, main  # noqa: E402

# --- Line 75: large-dof fall-through to the normal-z approximation -----------


def test_t_critical_uses_table_for_small_dof():
    assert _t_critical(1) == 12.706
    assert _t_critical(2) == 4.30265


def test_t_critical_falls_back_to_normal_z_for_large_dof():
    """dof beyond the vendored table (here 30) must use z=1.96, not crash."""
    assert _t_critical(30) == 1.96
    assert _t_critical(11) == 1.96  # 11 is the first dof past the table


def test_mean_ci_large_n_uses_normal_z():
    """With n>11 seeds the half-width must be computed from z=1.96 (dof=n-1
    is outside the Student-t table), exercising the fallback inside mean_ci.
    """
    scores = [0.5, 0.6] * 8  # n=16 -> dof=15, beyond the table
    mean, lower, upper = mean_ci(scores)
    stderr = statistics.stdev(scores) / math.sqrt(len(scores))
    expected_half = 1.96 * stderr
    assert math.isclose(upper - mean, expected_half, rel_tol=1e-9)
    assert math.isclose(mean - lower, expected_half, rel_tol=1e-9)


# --- Line 216: blank lines inside a .jsonl shard are skipped, not counted ----


def test_resolution_rate_skips_blank_lines(tmp_path):
    """Blank/whitespace lines between records must not inflate the total."""
    d = tmp_path / "artifacts"
    d.mkdir()
    body = (
        json.dumps({"task_id": "a", "resolved": True}) + "\n"
        "\n"  # blank line
        "   \n"  # whitespace-only line
        + json.dumps({"task_id": "b", "resolved": False}) + "\n"
    )
    (d / "shard.jsonl").write_text(body)
    rate, resolved, total = resolution_rate_from_run_artifacts(d)
    assert (resolved, total) == (1, 2)
    assert math.isclose(rate, 0.5)


def test_scores_from_run_artifacts_skips_empty_file(tmp_path):
    """A jsonl with no records contributes no score (the `if recs` guard)."""
    d = tmp_path / "artifacts"
    d.mkdir()
    _write_shard(d, "full.jsonl", [1, 1, 0])
    (d / "empty.jsonl").write_text("\n   \n")  # only blank lines -> no recs
    scores = scores_from_run_artifacts(d)
    assert scores == [2 / 3]  # empty file produced no entry


# --- Lines 264-302: main() across every branch -------------------------------


def _run_main(monkeypatch, argv, env=None):
    """Invoke main() with patched argv and a clean env, capturing SystemExit."""
    monkeypatch.setattr(sys, "argv", ["forgejudge.eval.gate", *argv])
    if env is not None:
        for k, v in env.items():
            if v is None:
                monkeypatch.delenv(k, raising=False)
            else:
                monkeypatch.setenv(k, v)
    else:
        monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    with pytest.raises(SystemExit) as exc:
        main()
    return exc.value.code


def test_main_seed_mode_pass_exits_zero(tmp_path, monkeypatch, capsys):
    baseline = tmp_path / "baseline.json"
    candidate = tmp_path / "candidate.json"
    baseline.write_text(json.dumps([0.6, 0.6, 0.6]))
    candidate.write_text(json.dumps([0.6, 0.6, 0.6]))
    code = _run_main(
        monkeypatch,
        ["--mode", "seed", "--baseline", str(baseline), "--candidate", str(candidate)],
    )
    assert code == 0
    assert "PASS" in capsys.readouterr().out


def test_main_seed_mode_regression_exits_one(tmp_path, monkeypatch, capsys):
    baseline = tmp_path / "baseline.json"
    candidate = tmp_path / "candidate.json"
    baseline.write_text(json.dumps([0.8, 0.82, 0.81, 0.79]))
    candidate.write_text(json.dumps([0.4, 0.42, 0.38, 0.41]))
    code = _run_main(
        monkeypatch,
        ["--mode", "seed", "--baseline", str(baseline), "--candidate", str(candidate)],
    )
    assert code == 1
    assert "FAIL" in capsys.readouterr().out


def test_main_seed_mode_candidate_from_run_artifacts(tmp_path, monkeypatch, capsys):
    """--candidate-runs path: scores are loaded per-file from the artifacts dir."""
    baseline = tmp_path / "baseline.json"
    baseline.write_text(json.dumps([0.9, 0.9, 0.9]))
    runs = tmp_path / "runs"
    runs.mkdir()
    # Two seed files, each a high rate -> overlaps baseline -> PASS.
    _write_shard(runs, "seed-0.jsonl", [1, 1, 1])
    _write_shard(runs, "seed-1.jsonl", [1, 1, 0])
    code = _run_main(
        monkeypatch,
        ["--mode", "seed", "--baseline", str(baseline), "--candidate-runs", str(runs)],
    )
    assert code == 0
    assert "PASS" in capsys.readouterr().out


def test_main_exact_mode_pass_exits_zero(tmp_path, monkeypatch, capsys):
    runs = tmp_path / "runs"
    runs.mkdir()
    _write_shard(runs, "shard-0.jsonl", [1, 1, 1])
    _write_shard(runs, "shard-1.jsonl", [1, 1, 1])
    code = _run_main(monkeypatch, ["--mode", "exact", "--candidate-runs", str(runs)])
    assert code == 0
    assert "PASS" in capsys.readouterr().out


def test_main_exact_mode_fail_exits_one(tmp_path, monkeypatch, capsys):
    runs = tmp_path / "runs"
    runs.mkdir()
    _write_shard(runs, "shard-0.jsonl", [1, 1, 0])
    code = _run_main(monkeypatch, ["--mode", "exact", "--candidate-runs", str(runs)])
    assert code == 1
    assert "FAIL" in capsys.readouterr().out


def test_main_exact_mode_requires_candidate_runs(monkeypatch):
    """--mode exact with no --candidate-runs must ap.error() (exit code 2)."""
    code = _run_main(monkeypatch, ["--mode", "exact"])
    assert code == 2


def test_main_seed_mode_requires_baseline(monkeypatch):
    """--mode seed with no --baseline must ap.error() (exit code 2)."""
    code = _run_main(monkeypatch, ["--mode", "seed"])
    assert code == 2


def test_main_seed_mode_requires_candidate_or_runs(tmp_path, monkeypatch):
    """--baseline given but neither --candidate nor --candidate-runs errors."""
    baseline = tmp_path / "baseline.json"
    baseline.write_text(json.dumps([0.6, 0.6, 0.6]))
    code = _run_main(monkeypatch, ["--mode", "seed", "--baseline", str(baseline)])
    assert code == 2


def test_main_writes_github_step_summary(tmp_path, monkeypatch):
    """When GITHUB_STEP_SUMMARY is set, main() appends a markdown badge block."""
    baseline = tmp_path / "baseline.json"
    candidate = tmp_path / "candidate.json"
    baseline.write_text(json.dumps([0.6, 0.6, 0.6]))
    candidate.write_text(json.dumps([0.6, 0.6, 0.6]))
    summary = tmp_path / "step_summary.md"
    code = _run_main(
        monkeypatch,
        ["--mode", "seed", "--baseline", str(baseline), "--candidate", str(candidate)],
        env={"GITHUB_STEP_SUMMARY": str(summary)},
    )
    assert code == 0
    written = summary.read_text()
    assert "### Regression gate:" in written
    assert "PASS" in written
    assert "```" in written  # fenced detail block


def test_main_step_summary_exact_mode_uses_gold_title(tmp_path, monkeypatch):
    """The summary heading switches to the gold title in exact mode, and the
    badge reflects a FAIL verdict.
    """
    runs = tmp_path / "runs"
    runs.mkdir()
    _write_shard(runs, "shard-0.jsonl", [1, 0, 1])
    summary = tmp_path / "step_summary.md"
    code = _run_main(
        monkeypatch,
        ["--mode", "exact", "--candidate-runs", str(runs)],
        env={"GITHUB_STEP_SUMMARY": str(summary)},
    )
    assert code == 1
    written = summary.read_text()
    assert "### Gold integrity gate:" in written
    assert "FAIL" in written


def test_main_default_mode_is_seed(tmp_path, monkeypatch, capsys):
    """No --mode flag defaults to seed mode (the argparse default)."""
    baseline = tmp_path / "baseline.json"
    candidate = tmp_path / "candidate.json"
    baseline.write_text(json.dumps([0.5, 0.5]))
    candidate.write_text(json.dumps([0.9, 0.9]))
    code = _run_main(
        monkeypatch,
        ["--baseline", str(baseline), "--candidate", str(candidate)],
    )
    assert code == 0
    assert "PASS" in capsys.readouterr().out


# --- Line 306: module run as __main__ exercises the script guard ------------


def test_module_run_as_main_invokes_main(tmp_path, monkeypatch):
    """Running the module with ``run_name='__main__'`` exercises the guard.

    ``runpy.run_module`` re-executes the module body in-process (so coverage
    sees line 306) with ``__name__ == '__main__'``, which calls ``main()``. A
    real regression makes main() exit non-zero, proving the guard fired.
    """
    baseline = tmp_path / "baseline.json"
    candidate = tmp_path / "candidate.json"
    baseline.write_text(json.dumps([0.8, 0.82, 0.81, 0.79]))
    candidate.write_text(json.dumps([0.4, 0.42, 0.38, 0.41]))
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "forgejudge.eval.gate",
            "--mode",
            "seed",
            "--baseline",
            str(baseline),
            "--candidate",
            str(candidate),
        ],
    )
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    with pytest.raises(SystemExit) as exc, warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        runpy.run_module("forgejudge.eval.gate", run_name="__main__")
    assert exc.value.code == 1
