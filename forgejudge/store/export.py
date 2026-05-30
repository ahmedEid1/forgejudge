"""Export a JSON snapshot of the leaderboard + runs from Neon for the static
dashboard. Snapshotting (vs querying at request time) keeps the public site
always-on and $0 — it renders historical runs even when live quotas are spent.
"""

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path

from forgejudge.store.db import connect, leaderboard

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_OUT = REPO_ROOT / "dashboard" / "public" / "data"

_RUNS_SQL = """
    SELECT r.run_id, r.task_id, r.model, r.scaffold_version, r.seed, r.resolved,
           r.f2p_passed, r.f2p_total, r.p2p_passed, r.p2p_total,
           r.tokens_in, r.tokens_out, r.cost_usd, r.wall_clock_s, r.trace_url, r.judge_score,
           r.status, r.created_at, COALESCE(t.problem_statement, ''), r.patch
    FROM runs r LEFT JOIN tasks t ON t.instance_id = r.task_id
    ORDER BY r.model, r.task_id, r.seed
"""
_RUN_COLS = ["run_id", "task_id", "model", "scaffold_version", "seed", "resolved",
             "f2p_passed", "f2p_total", "p2p_passed", "p2p_total", "tokens_in",
             "tokens_out", "cost_usd", "wall_clock_s", "trace_url", "judge_score",
             "status", "created_at", "problem_statement", "patch"]


def read_calibration(out_dir: str | Path = DEFAULT_OUT) -> dict | None:
    """Read the judge calibration snapshot if present, else ``None``.

    The canonical ``calibration.json`` (kappa, n, confusion) is written
    separately by :mod:`forgejudge.eval.calibrate`; this is a read-only reflect
    so the exporter summary can surface the judge's κ without recomputing it
    (the live LLM pass is run by the operator, never here).
    """
    path = Path(out_dir) / "calibration.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return None


def export_snapshot(out_dir: str | Path = DEFAULT_OUT, *, now: str | None = None) -> dict:
    """Write ``leaderboard.json`` and ``runs.json`` to ``out_dir``; return a summary."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    conn = connect()
    try:
        board = leaderboard(conn)
        n_tasks = conn.execute("SELECT count(*) FROM tasks").fetchone()[0]
        runs = [dict(zip(_RUN_COLS, r, strict=True)) for r in conn.execute(_RUNS_SQL).fetchall()]
    finally:
        conn.close()

    generated_at = now or datetime.now(UTC).isoformat()
    (out_dir / "leaderboard.json").write_text(
        json.dumps({"generated_at": generated_at, "n_tasks": n_tasks, "models": board}, indent=2)
    )
    (out_dir / "runs.json").write_text(json.dumps({"generated_at": generated_at, "runs": runs}, indent=2))
    # Reflect (do not recompute) the judge calibration, if it has been published.
    calibration = read_calibration(out_dir)
    summary = {"models": len(board), "runs": len(runs), "n_tasks": n_tasks, "out": str(out_dir)}
    if calibration is not None:
        summary["judge_kappa"] = calibration.get("kappa")
    return summary


def main() -> None:
    ap = argparse.ArgumentParser(description="Export leaderboard JSON snapshot from Neon")
    ap.add_argument("--out", default=str(DEFAULT_OUT))
    args = ap.parse_args()
    summary = export_snapshot(args.out)
    print(f"exported {summary['models']} model(s), {summary['runs']} run(s) -> {summary['out']}")


if __name__ == "__main__":
    main()
