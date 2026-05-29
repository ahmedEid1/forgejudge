"""Run the agent over every task x seed, grade each patch, persist RunRecords.

Scheduled by .github/workflows/sweep.yml. ``run_sweep(model, seeds)`` powers the
leaderboard and the model-swap comparison (same harness, swap the model).
"""

import argparse
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from forgejudge import __version__
from forgejudge.agent.solver import solve
from forgejudge.golden.loader import load_tasks
from forgejudge.harness.grade import grade
from forgejudge.llm.router import complete
from forgejudge.types import RunRecord, Task

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DATASET = REPO_ROOT / "golden" / "dataset.jsonl"


@dataclass
class SweepResult:
    model: str
    records: list[RunRecord]

    @property
    def resolution_rate(self) -> float:
        if not self.records:
            return 0.0
        return sum(r.resolved for r in self.records) / len(self.records)


def forced_model_complete(model: str):
    """A complete_fn that forces every call onto ``model`` (model-swap)."""
    def fn(messages, *, role, run_id):
        return complete(messages, role=role, run_id=run_id, model=model)
    return fn


def run_sweep(
    model: str,
    seeds: list[int],
    *,
    tasks: list[Task] | None = None,
    dataset: str | Path = DATASET,
    budget_usd: float = 0.10,
    max_steps: int = 6,
    complete_fn=None,
    store_conn=None,
    scaffold_version: str = __version__,
    now: str | None = None,
) -> SweepResult:
    """Solve + grade every (task, seed); persist each RunRecord if ``store_conn``."""
    tasks = tasks if tasks is not None else load_tasks(dataset)
    cfn = complete_fn or forced_model_complete(model)
    records: list[RunRecord] = []
    for task in tasks:
        for seed in seeds:
            run_id = f"{model}-{task.instance_id}-seed{seed}"
            t0 = time.perf_counter()
            sr = solve(task, run_id=run_id, budget_usd=budget_usd, seed=seed,
                       max_steps=max_steps, complete_fn=cfn)
            grade_res = grade(task, sr.patch)
            wall = time.perf_counter() - t0
            rec = RunRecord(
                run_id=run_id, task_id=task.instance_id, model=model,
                scaffold_version=scaffold_version, seed=seed, resolved=grade_res.resolved,
                grade=grade_res, patch=sr.patch, tokens_in=sr.tokens_in, tokens_out=sr.tokens_out,
                cost_usd=sr.cost_usd, wall_clock_s=round(wall, 3), trace_url=sr.trace_url,
                status=sr.status, created_at=now or datetime.now(UTC).isoformat(),
            )
            records.append(rec)
            if store_conn is not None:
                from forgejudge.store.db import insert_run

                insert_run(store_conn, rec)
    return SweepResult(model, records)


def main() -> None:
    ap = argparse.ArgumentParser(description="ForgeJudge scheduled eval sweep")
    ap.add_argument("--model", required=True, help="litellm model id (e.g. groq/llama-3.3-70b-versatile)")
    ap.add_argument("--seeds", default="0", help="comma-separated seeds")
    ap.add_argument("--budget-usd", type=float, default=0.10)
    ap.add_argument("--max-steps", type=int, default=6)
    ap.add_argument("--no-store", action="store_true", help="do not write to the DB")
    ap.add_argument("--out", default="", help="also write RunRecords to this jsonl")
    args = ap.parse_args()

    seeds = [int(s) for s in args.seeds.split(",") if s.strip()]
    conn = None
    if not args.no_store:
        from forgejudge.store.db import connect, init_db, upsert_tasks

        conn = connect()
        init_db(conn)
        tasks = load_tasks(DATASET)
        upsert_tasks(conn, tasks)

    result = run_sweep(args.model, seeds, budget_usd=args.budget_usd,
                       max_steps=args.max_steps, store_conn=conn)
    if args.out:
        Path(args.out).write_text("".join(r.model_dump_json() + "\n" for r in result.records))
    print(f"sweep model={args.model} seeds={seeds}: "
          f"resolution_rate={result.resolution_rate:.3f} over {len(result.records)} runs")
    if conn is not None:
        conn.close()


if __name__ == "__main__":
    main()
