"""Calibrate the LLM-as-judge against human gold labels and publish the result.

The judge (:mod:`forgejudge.eval.judge`) emits a discrete 1-5 quality score; the
human gold set (``golden/judge_gold.jsonl``) carries a human 1-5 ``human_score``
for the same patches. To report *trustworthy* agreement we binarize both onto a
single good/bad **verdict** (score ``>= GOOD_THRESHOLD`` is "good") and compute
**Cohen's kappa** — chance-corrected agreement — using the existing
:func:`forgejudge.eval.judge.cohen_kappa` (imported, never reimplemented).

The pure :func:`compute_calibration` does no I/O and no LLM call; it just turns
``(judge_verdict, reference_verdict)`` pairs into ``{kappa, n, agreement,
confusion, by_label}``. The CLI (:func:`main`) wires the live pieces: it loads
the gold rows, runs the judge over each (reusing :func:`judge.judge_patch` with
an injectable ``complete_fn`` so tests never touch a real LLM), pairs the judge
verdict against the human reference verdict, and writes the canonical artifact
``dashboard/public/data/calibration.json`` that the calibration page renders.

The judge remains SECONDARY (see ``PRIMARY_GATE`` in :mod:`forgejudge.eval.judge`):
kappa is published only so the qualitative score is held to the same evidence bar
as the deterministic gate — it never decides pass/fail.
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Callable, Iterable
from datetime import UTC, datetime
from pathlib import Path

from forgejudge.eval.judge import cohen_kappa, judge_patch, load_judge_gold

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_GOLD = REPO_ROOT / "golden" / "judge_gold.jsonl"
DEFAULT_OUT = REPO_ROOT / "dashboard" / "public" / "data" / "calibration.json"

# A discrete 1-5 score at or above this is a "good" (positive) verdict. Gold
# patches are human-labelled 4-5, deliberately bad ones 1-2, so the threshold
# cleanly separates the seed set.
GOOD_THRESHOLD = 4


def score_to_verdict(score: int) -> bool:
    """Binarize a discrete 1-5 quality score to a good/bad verdict."""
    return score >= GOOD_THRESHOLD


def compute_calibration(pairs: Iterable[tuple[bool, bool]]) -> dict:
    """Summarize judge-vs-reference agreement over good/bad ``(judge, ref)`` pairs.

    ``pairs`` is an iterable of ``(judge_verdict, reference_verdict)`` booleans
    (``True`` == "good"). Returns a JSON-serializable dict:

    * ``kappa`` — Cohen's kappa (chance-corrected agreement), via
      :func:`forgejudge.eval.judge.cohen_kappa`; ``None`` when there are no pairs.
    * ``n`` — number of pairs.
    * ``agreement`` — raw observed agreement proportion in ``[0, 1]``.
    * ``confusion`` — ``{tp, fp, fn, tn}`` with the reference verdict as ground
      truth (positive == "good").
    * ``by_label`` — per-verdict counts and recall, keyed ``"good"`` / ``"bad"``.
    """
    pairs = list(pairs)
    n = len(pairs)
    if n == 0:
        return {
            "kappa": None,
            "n": 0,
            "agreement": None,
            "confusion": {"tp": 0, "fp": 0, "fn": 0, "tn": 0},
            "by_label": {
                "good": {"reference": 0, "judge": 0, "correct": 0, "recall": None},
                "bad": {"reference": 0, "judge": 0, "correct": 0, "recall": None},
            },
        }

    tp = fp = fn = tn = 0
    for judge_v, ref_v in pairs:
        if ref_v and judge_v:
            tp += 1
        elif ref_v and not judge_v:
            fn += 1
        elif not ref_v and judge_v:
            fp += 1
        else:
            tn += 1

    # Reuse the canonical kappa. Map verdicts onto 1 (good) / 0 (bad) ints.
    judge_codes = [1 if j else 0 for j, _ in pairs]
    ref_codes = [1 if r else 0 for _, r in pairs]
    kappa = cohen_kappa(judge_codes, ref_codes)

    agreement = (tp + tn) / n
    ref_good = tp + fn
    ref_bad = fp + tn

    def _recall(correct: int, total: int) -> float | None:
        return correct / total if total else None

    by_label = {
        "good": {
            "reference": ref_good,
            "judge": tp + fp,
            "correct": tp,
            "recall": _recall(tp, ref_good),
        },
        "bad": {
            "reference": ref_bad,
            "judge": fn + tn,
            "correct": tn,
            "recall": _recall(tn, ref_bad),
        },
    }

    return {
        "kappa": kappa,
        "n": n,
        "agreement": agreement,
        "confusion": {"tp": tp, "fp": fp, "fn": fn, "tn": tn},
        "by_label": by_label,
    }


def _patch_for_row(row: dict, solutions: dict[str, str]) -> str:
    """Resolve the patch to judge for one gold row.

    A ``patch_kind == "gold"`` row is judged against the validated reference
    ``gold_patch`` from ``golden/solutions.jsonl``. A ``"bad"`` row has no
    reference patch in the repo, so it is judged as an empty patch — the judge's
    empty-patch shortcut scores it the minimum (1, "bad"), which is the correct
    reference verdict for a deliberately-bad row. An explicit ``patch`` field on
    the row, if present, always wins.
    """
    if row.get("patch") is not None:
        return row["patch"]
    if row.get("patch_kind") == "gold":
        return solutions.get(row["instance_id"], "")
    return ""


def run_calibration(
    *,
    gold_path: str | Path = DEFAULT_GOLD,
    complete_fn: Callable | None = None,
    model: str = "judge",
) -> dict:
    """Run the judge over the gold set and compute the calibration summary.

    ``complete_fn`` is injected straight into :func:`judge.judge_patch` (tests
    pass a fake; production passes the live router). Network/DB are touched ONLY
    if a real ``complete_fn`` actually calls out — the function itself does none.
    Returns the :func:`compute_calibration` dict plus ``generated_at`` + ``model``.
    """
    # Local imports keep the pure compute path (and ``--help``) free of any
    # golden-loader / dataset dependency.
    from forgejudge.golden.build_dataset import load_solutions
    from forgejudge.golden.loader import load_tasks

    rows = load_judge_gold(gold_path)
    tasks = {t.instance_id: t for t in load_tasks(REPO_ROOT / "golden" / "dataset.jsonl")}
    solutions = load_solutions()

    judge_kwargs = {} if complete_fn is None else {"complete_fn": complete_fn}

    pairs: list[tuple[bool, bool]] = []
    for i, row in enumerate(rows):
        task = tasks.get(row["instance_id"])
        if task is None:
            raise ValueError(
                f"judge gold references unknown instance_id {row['instance_id']!r}"
            )
        patch = _patch_for_row(row, solutions)
        scored = judge_patch(task, patch, run_id=f"calib-{i}", **judge_kwargs)
        judge_verdict = score_to_verdict(scored.score)
        reference_verdict = score_to_verdict(int(row["human_score"]))
        pairs.append((judge_verdict, reference_verdict))

    summary = compute_calibration(pairs)
    summary["generated_at"] = datetime.now(UTC).isoformat()
    summary["model"] = model
    return summary


def write_calibration(summary: dict, out_path: str | Path = DEFAULT_OUT) -> Path:
    """Write ``summary`` to ``out_path`` as pretty JSON; return the path."""
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    ordered = {
        "generated_at": summary.get("generated_at"),
        "model": summary.get("model"),
        "kappa": summary.get("kappa"),
        "n": summary.get("n"),
        "agreement": summary.get("agreement"),
        "confusion": summary.get("confusion"),
        "by_label": summary.get("by_label"),
    }
    out_path.write_text(json.dumps(ordered, indent=2) + "\n")
    return out_path


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(
        description=(
            "Calibrate the LLM-as-judge against golden/judge_gold.jsonl and write "
            "dashboard/public/data/calibration.json (Cohen's kappa). Runs the live "
            "judge model unless --dry-run."
        )
    )
    ap.add_argument("--gold", default=str(DEFAULT_GOLD), help="path to judge_gold.jsonl")
    ap.add_argument("--out", default=str(DEFAULT_OUT), help="output calibration.json path")
    ap.add_argument(
        "--model", default="judge", help="model label recorded in the artifact"
    )
    ap.add_argument(
        "--dry-run",
        action="store_true",
        help="skip the live judge; emit a zeroed empty-state artifact (no network)",
    )
    args = ap.parse_args(argv)

    if args.dry_run:
        summary = compute_calibration([])
        summary["generated_at"] = datetime.now(UTC).isoformat()
        summary["model"] = args.model
    else:
        # The live judge pass calls the real LLM router (network) — guarded behind
        # the explicit, non-default code path so --help/--dry-run need no key.
        summary = run_calibration(gold_path=args.gold, model=args.model)

    out = write_calibration(summary, args.out)
    k = summary.get("kappa")
    k_str = "—" if k is None else f"{k:.3f}"
    print(f"calibration: kappa={k_str} n={summary.get('n')} -> {out}")


if __name__ == "__main__":
    main()
