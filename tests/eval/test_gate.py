"""The CI regression gate (spec decision #12): only a statistically real,
CI-separated drop in per-seed resolution rate should block a change. Identical,
overlapping, flaky-but-overlapping, and improved runs must all pass.
"""

import math

import pytest

from forgejudge.eval.gate import GateResult, mean_ci, regression_gate


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
