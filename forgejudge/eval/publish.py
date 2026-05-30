"""Quality-gated leaderboard publish.

The scheduled sweep writes one ``runs-<model>.jsonl`` per model (``--no-store
--out``). Publishing then (a) refuses to persist a model whose sweep visibly
degraded — e.g. a free-tier daily-token-limit storm that turns most runs into
``status="error"`` — so a flaky run can never overwrite good numbers with
garbage, (b) upserts the runs of every model that passed the gate into Neon, and
(c) re-exports the static JSON snapshot the dashboard serves.

A *skipped* model keeps whatever data it already had in Neon, so the leaderboard
degrades gracefully (stale-but-honest) instead of publishing a rate-limited dip.
"""

from __future__ import annotations

import argparse
import glob
from collections import Counter
from pathlib import Path

from forgejudge.store.export import export_snapshot
from forgejudge.types import RunRecord

DEFAULT_MAX_ERROR_RATE = 0.25


def load_runs(path: str | Path) -> list[RunRecord]:
    """Load ``RunRecord``s from a ``model_dump_json``-per-line ``.jsonl`` file."""
    return [
        RunRecord.model_validate_json(line)
        for line in Path(path).read_text().splitlines()
        if line.strip()
    ]


def error_rate(records: list[RunRecord]) -> float:
    """Fraction of runs that ended in ``status == "error"`` (0.0 for an empty list)."""
    if not records:
        return 0.0
    return sum(1 for r in records if r.status == "error") / len(records)


def model_of(records: list[RunRecord]) -> str:
    """The dominant model id across ``records`` (for reporting/grouping)."""
    names = Counter(r.model for r in records if r.model)
    return names.most_common(1)[0][0] if names else "unknown"


def gate(records: list[RunRecord], *, max_error_rate: float = DEFAULT_MAX_ERROR_RATE) -> tuple[bool, str]:
    """Decide whether a model's sweep is healthy enough to publish."""
    if not records:
        return False, "empty"
    er = error_rate(records)
    if er > max_error_rate:
        return False, f"degraded: error_rate {er:.2f} > {max_error_rate:.2f} (likely rate-limited)"
    return True, f"ok: error_rate {er:.2f}"


def publish(
    run_files: list[str | Path],
    *,
    conn,
    out_dir: str | Path | None = None,
    max_error_rate: float = DEFAULT_MAX_ERROR_RATE,
    now: str | None = None,
    do_export: bool = True,
) -> dict:
    """Quality-gate each file, upsert the healthy ones into ``conn``, then export.

    ``conn`` is an open DB connection (so callers control which DB is touched).
    Returns a report: which models were published vs skipped, and the export summary.
    """
    from forgejudge.store.db import insert_runs

    report: dict = {"published": [], "skipped": [], "exported": False}
    healthy: list[RunRecord] = []
    for path in run_files:
        recs = load_runs(path)
        ok, reason = gate(recs, max_error_rate=max_error_rate)
        entry = {"file": str(path), "model": model_of(recs), "n": len(recs),
                 "error_rate": round(error_rate(recs), 3), "reason": reason}
        if ok:
            healthy.extend(recs)
            report["published"].append(entry)
        else:
            report["skipped"].append(entry)

    if healthy:
        insert_runs(conn, healthy)

    if do_export:
        report["export"] = export_snapshot(out_dir, now=now) if out_dir else export_snapshot(now=now)
        report["exported"] = True
    return report


def main() -> None:
    ap = argparse.ArgumentParser(description="Quality-gated leaderboard publish (insert healthy sweeps + export)")
    ap.add_argument("--runs", required=True, help="glob for runs-*.jsonl files, e.g. 'runs-*.jsonl'")
    ap.add_argument("--max-error-rate", type=float, default=DEFAULT_MAX_ERROR_RATE)
    ap.add_argument("--out", default="", help="dashboard data dir (default: package default)")
    ap.add_argument("--no-export", action="store_true")
    args = ap.parse_args()

    files = sorted(glob.glob(args.runs))
    if not files:
        raise SystemExit(f"no run files matched {args.runs!r}")

    from forgejudge.store.db import connect, init_db

    conn = connect()
    init_db(conn)
    try:
        report = publish(
            files, conn=conn, out_dir=(args.out or None),
            max_error_rate=args.max_error_rate, do_export=not args.no_export,
        )
    finally:
        conn.close()

    for e in report["published"]:
        print(f"  published {e['model']:32} n={e['n']} {e['reason']}")
    for e in report["skipped"]:
        print(f"  SKIPPED   {e['model']:32} n={e['n']} {e['reason']}")
    if report["exported"]:
        ex = report["export"]
        print(f"exported {ex['models']} model(s), {ex['runs']} run(s), {ex['n_tasks']} tasks -> {ex['out']}")
    if not report["published"]:
        raise SystemExit("publish: every model was gated out — nothing published (failing so CI is visibly red)")


if __name__ == "__main__":
    main()
