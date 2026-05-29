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

import argparse
import json
import math
import os
import statistics
import sys
from dataclasses import dataclass
from pathlib import Path


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


def scores_from_run_artifacts(artifacts_dir: str | Path) -> list[float]:
    """Per-shard resolution rates from RunRecord ``*.jsonl`` files (one score each)."""
    scores: list[float] = []
    for p in sorted(Path(artifacts_dir).rglob("*.jsonl")):
        recs = [json.loads(line) for line in p.read_text().splitlines() if line.strip()]
        if recs:
            scores.append(sum(1 for r in recs if r.get("resolved")) / len(recs))
    return scores


def main() -> None:
    ap = argparse.ArgumentParser(description="ForgeJudge multi-seed regression gate")
    ap.add_argument("--baseline", required=True, help="JSON file: list of baseline per-seed scores")
    ap.add_argument("--candidate", help="JSON file: list of candidate per-seed scores")
    ap.add_argument("--candidate-runs", help="dir of RunRecord *.jsonl (per-file resolution rates)")
    ap.add_argument("--z", type=float, default=1.96)
    args = ap.parse_args()

    baseline = json.loads(Path(args.baseline).read_text())
    if args.candidate:
        candidate = json.loads(Path(args.candidate).read_text())
    elif args.candidate_runs:
        candidate = scores_from_run_artifacts(args.candidate_runs)
    else:
        ap.error("provide --candidate or --candidate-runs")

    result = regression_gate(baseline, candidate, z=args.z)
    print(result.detail)
    summary = os.getenv("GITHUB_STEP_SUMMARY")
    if summary:
        badge = "✅ PASS" if result.passed else "❌ FAIL"
        with Path(summary).open("a") as fh:
            fh.write(f"### Regression gate: {badge}\n\n```\n{result.detail}\n```\n")
    sys.exit(0 if result.passed else 1)


if __name__ == "__main__":
    main()
