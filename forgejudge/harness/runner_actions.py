"""Grade a shard of golden tasks and emit RunRecord artifacts (used by eval.yml).

In Phase 2 this grades the GOLD patches as an end-to-end harness self-test — in
the ephemeral GitHub Actions VM (the sandbox boundary), every task must resolve.
The Phase 5 sweep reuses :func:`grade_tasks` with the agent's patches.
"""

import argparse
import json
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

from forgejudge import __version__
from forgejudge.golden.build_dataset import load_solutions
from forgejudge.golden.loader import load_tasks
from forgejudge.harness.grade import grade
from forgejudge.types import RunRecord

# Absolute default so the bundled dataset is found regardless of cwd (e.g. when the
# installed package's `forgejudge selftest` runs from an arbitrary directory).
DEFAULT_DATASET = Path(__file__).resolve().parent.parent.parent / "golden" / "dataset.jsonl"


def select_shard(tasks: list, shard: int, num_shards: int) -> list:
    """Round-robin partition (balances task cost across shards)."""
    return [t for i, t in enumerate(tasks) if i % num_shards == shard]


def grade_tasks(
    tasks: list, patches: dict[str, str], *, model: str, seed: int, now: str | None = None
) -> list[RunRecord]:
    created = now or datetime.now(UTC).isoformat()
    records: list[RunRecord] = []
    for t in tasks:
        patch = patches.get(t.instance_id, "")
        t0 = time.perf_counter()
        result = grade(t, patch)
        wall = time.perf_counter() - t0
        records.append(
            RunRecord(
                run_id=f"{model}-{t.instance_id}-seed{seed}",
                task_id=t.instance_id,
                model=model,
                scaffold_version=__version__,
                seed=seed,
                resolved=result.resolved,
                grade=result,
                patch=patch,
                tokens_in=0,
                tokens_out=0,
                cost_usd=0.0,
                wall_clock_s=round(wall, 3),
                trace_url="",
                status="ok",
                created_at=created,
            )
        )
    return records


def aggregate(artifacts_dir: str | Path, out: str | Path) -> tuple[int, int]:
    """Concatenate all shard ``*.jsonl`` into ``out``; return (resolved, total)."""
    resolved, total, _ = _aggregate(artifacts_dir, out)
    return resolved, total


def _aggregate(artifacts_dir: str | Path, out: str | Path) -> tuple[int, int, bool]:
    """Like :func:`aggregate` but also report whether any record is a gold run.

    The standalone eval.yml self-test feeds ``--patch-source gold`` shards in here;
    a gold run where ``resolved != total`` means a gold patch stopped resolving and
    the self-test must fail (see finding #36)."""
    records = []
    for p in sorted(Path(artifacts_dir).rglob("*.jsonl")):
        records += [json.loads(line) for line in p.read_text().splitlines() if line.strip()]
    Path(out).write_text("".join(json.dumps(r) + "\n" for r in records))
    resolved = sum(1 for r in records if r.get("resolved"))
    is_gold = any(r.get("model") == "gold" for r in records)
    return resolved, len(records), is_gold


def main() -> None:
    ap = argparse.ArgumentParser(description="ForgeJudge sandbox grade executor")
    ap.add_argument("--dataset", default=str(DEFAULT_DATASET))
    ap.add_argument("--patch-source", choices=["gold", "empty"], default="gold")
    ap.add_argument("--shard", type=int, default=0)
    ap.add_argument("--num-shards", type=int, default=1)
    ap.add_argument("--model", default="gold")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--out", default="runs.jsonl")
    ap.add_argument("--aggregate", metavar="DIR", help="aggregate shard artifacts in DIR")
    args = ap.parse_args()

    if args.aggregate:
        resolved, total, is_gold = _aggregate(args.aggregate, args.out)
        print(f"aggregate: {resolved}/{total} resolved -> {args.out}")
        # Self-test guarantee: a gold run MUST resolve every task; otherwise a
        # gold patch silently regressed and eval.yml must go red (#36).
        if is_gold and resolved != total:
            print(f"FAIL: gold self-test expected {total}/{total} resolved, got {resolved}")
            sys.exit(1)
        return

    tasks = select_shard(load_tasks(args.dataset), args.shard, args.num_shards)
    patches = load_solutions() if args.patch_source == "gold" else {}
    records = grade_tasks(tasks, patches, model=args.model, seed=args.seed)
    Path(args.out).write_text("".join(r.model_dump_json() + "\n" for r in records))
    resolved = sum(1 for r in records if r.resolved)
    print(f"shard {args.shard}/{args.num_shards} [{args.patch_source}]: "
          f"{resolved}/{len(records)} resolved -> {args.out}")
    # With --patch-source gold this shard is the harness self-test: every task
    # must resolve, so a non-resolution is a hard failure, not a silent print (#36).
    if args.patch_source == "gold" and resolved != len(records):
        unresolved = [r.task_id for r in records if not r.resolved]
        print(f"FAIL: gold self-test left tasks unresolved: {unresolved}")
        sys.exit(1)


if __name__ == "__main__":
    main()
