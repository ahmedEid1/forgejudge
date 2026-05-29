"""Multi-seed CI regression gate (spec decision #12).

A model swap / scaffold change should only be *blocked* when it is
statistically — not merely noisily — worse than the baseline. We run each
side over several seeds, turn the per-seed resolution rates into a normal
confidence interval (mean +/- z * standard error), and fail the gate IFF the
candidate's upper bound sits strictly below the baseline's lower bound. Equal,
overlapping, flaky-but-overlapping, or improved distributions all pass.

Pure standard library: no scipy/numpy. The CI is the usual large-sample normal
approximation, which is plenty for a coarse "did we regress" guard.
"""

import math
import statistics
from dataclasses import dataclass


def mean_ci(scores: list[float], z: float = 1.96) -> tuple[float, float, float]:
    """Return ``(mean, lower, upper)`` for a list of per-seed scores.

    The interval is ``mean +/- z * (sample_stdev / sqrt(n))``. With fewer than
    two samples there is no spread to estimate, so we degenerate to a
    zero-width interval at the mean. An empty list is treated as mean ``0.0``
    (also a zero-width interval), so a missing side never crashes the gate.
    """
    if not scores:
        return 0.0, 0.0, 0.0
    mean = statistics.mean(scores)
    n = len(scores)
    if n < 2:
        # Single seed: no variance estimate available, so the CI collapses to
        # the point estimate rather than fabricating a spread.
        return mean, mean, mean
    stderr = statistics.stdev(scores) / math.sqrt(n)
    half = z * stderr
    return mean, mean - half, mean + half


@dataclass
class GateResult:
    """Verdict of the regression gate for one candidate vs one baseline."""

    passed: bool
    detail: str
    baseline_mean: float
    candidate_mean: float
    baseline_lower: float
    candidate_upper: float


def regression_gate(
    baseline_scores: list[float],
    candidate_scores: list[float],
    *,
    z: float = 1.96,
) -> GateResult:
    """Decide whether ``candidate`` is a statistically real regression.

    ``*_scores`` are per-seed resolution rates (each in ``[0, 1]``). We build a
    normal CI for each side and FAIL only when the candidate's *upper* bound is
    strictly below the baseline's *lower* bound — i.e. even being generous to
    the candidate and harsh to the baseline, the candidate still loses. Equal,
    overlapping, or improved distributions pass; one flaky low seed that widens
    the candidate CI enough to overlap does not fail.

    Both sides empty is a contract violation and raises ``ValueError``; a single
    empty side is tolerated (treated as a mean of ``0.0``).
    """
    if not baseline_scores and not candidate_scores:
        raise ValueError("regression_gate: both score lists are empty")

    baseline_mean, baseline_lower, _baseline_upper = mean_ci(baseline_scores, z)
    candidate_mean, _candidate_lower, candidate_upper = mean_ci(candidate_scores, z)

    passed = not (candidate_upper < baseline_lower)
    if passed:
        verdict = (
            f"PASS: candidate CI upper {candidate_upper:.4f} is not below "
            f"baseline CI lower {baseline_lower:.4f}; the intervals overlap or "
            f"the candidate is better (no statistically significant regression)"
        )
    else:
        verdict = (
            f"FAIL: candidate CI upper {candidate_upper:.4f} < baseline CI "
            f"lower {baseline_lower:.4f}; the candidate is statistically worse "
            f"(regression, not noise)"
        )
    detail = (
        f"{verdict}. baseline mean={baseline_mean:.4f} lower={baseline_lower:.4f}; "
        f"candidate mean={candidate_mean:.4f} upper={candidate_upper:.4f}; z={z}"
    )
    return GateResult(
        passed=passed,
        detail=detail,
        baseline_mean=baseline_mean,
        candidate_mean=candidate_mean,
        baseline_lower=baseline_lower,
        candidate_upper=candidate_upper,
    )
