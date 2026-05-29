"""Build & validate the golden-set dataset from fixture/owned directory states.

Scans ``fixtures/`` (and optionally ``owned/``), derives the ``test_patch`` and
the reference ``gold_patch`` for each task with git, *validates* each by actually
running pytest (the failing test must FAIL on buggy base and PASS after the gold
fix, with PASS_TO_PASS staying green), then emits:

* ``golden/dataset.jsonl``   — one :class:`Task` per line (canonical, committed)
* ``golden/solutions.jsonl`` — ``{instance_id, gold_patch}`` sidecar (tests only)
"""

import json
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path

import yaml

from forgejudge.golden.loader import validate_dataset
from forgejudge.golden.materialize import (
    apply_unified_diff,
    copy_tree,
    init_base_repo,
    reset_to_base,
    run_nodeids,
    staged_diff_against_base,
)
from forgejudge.types import Task

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
FIXTURES_ROOT = REPO_ROOT / "forgejudge" / "golden" / "fixtures"
OWNED_ROOT = REPO_ROOT / "golden" / "owned"
DATASET_PATH = REPO_ROOT / "golden" / "dataset.jsonl"
SOLUTIONS_PATH = REPO_ROOT / "golden" / "solutions.jsonl"


@dataclass
class FixtureValidation:
    buggy_f2p_passed: int
    f2p_total: int
    buggy_p2p_passed: int
    golden_f2p_passed: int
    golden_p2p_passed: int
    p2p_total: int
    logs: str

    @property
    def is_valid(self) -> bool:
        return (
            self.f2p_total > 0
            and self.buggy_f2p_passed == 0           # failing test really fails on buggy base
            and self.buggy_p2p_passed == self.p2p_total   # existing tests pass on base
            and self.golden_f2p_passed == self.f2p_total  # gold fix turns it green
            and self.golden_p2p_passed == self.p2p_total  # gold fix breaks nothing
        )


def _read_meta(task_dir: Path) -> dict:
    meta = yaml.safe_load((task_dir / "meta.yaml").read_text())
    if not isinstance(meta, dict):
        raise ValueError(f"{task_dir}/meta.yaml is not a mapping")
    return meta


def build_task(task_dir: Path) -> tuple[Task, str]:
    """Derive the (Task, gold_patch) for a fixture/owned directory."""
    meta = _read_meta(task_dir)
    name = task_dir.name
    tmp = Path(tempfile.mkdtemp(prefix=f"fjbuild-{name}-"))
    try:
        copy_tree(task_dir / "base", tmp)
        init_base_repo(tmp)

        copy_tree(task_dir / "test", tmp)
        test_patch = staged_diff_against_base(tmp)
        reset_to_base(tmp)

        copy_tree(task_dir / "fix", tmp)
        gold_patch = staged_diff_against_base(tmp)
        reset_to_base(tmp)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    task = Task(
        instance_id=meta["instance_id"],
        family=meta["family"],
        repo=meta.get("repo", f"fixture:{name}"),
        base_commit=meta.get("base_commit", ""),
        problem_statement=meta["problem_statement"].strip(),
        test_patch=test_patch,
        fail_to_pass=list(meta["fail_to_pass"]),
        pass_to_pass=list(meta["pass_to_pass"]),
        env_image=meta.get("env_image", "python:3.12-slim"),
        source_license=meta.get("source_license", "own"),
        created_at=str(meta["created_at"]),
    )
    return task, gold_patch


def validate_task(task: Task, gold_patch: str, task_dir: Path) -> FixtureValidation:
    """Run pytest to prove buggy->FAIL and gold->PASS for ``task``.

    The buggy and gold phases run in *separate* trees so an in-place patch can
    never be shadowed by a stale interpreter/bytecode cache from a prior phase.
    """
    buggy = Path(tempfile.mkdtemp(prefix=f"fjval-buggy-{task_dir.name}-"))
    gold = Path(tempfile.mkdtemp(prefix=f"fjval-gold-{task_dir.name}-"))
    try:
        copy_tree(task_dir / "base", buggy)
        init_base_repo(buggy)
        apply_unified_diff(buggy, task.test_patch)
        buggy_f2p, f2p_total, l1 = run_nodeids(buggy, task.fail_to_pass)
        buggy_p2p, p2p_total, l2 = run_nodeids(buggy, task.pass_to_pass)

        copy_tree(task_dir / "base", gold)
        init_base_repo(gold)
        apply_unified_diff(gold, task.test_patch)
        apply_unified_diff(gold, gold_patch)
        gold_f2p, _, l3 = run_nodeids(gold, task.fail_to_pass)
        gold_p2p, _, l4 = run_nodeids(gold, task.pass_to_pass)
    finally:
        shutil.rmtree(buggy, ignore_errors=True)
        shutil.rmtree(gold, ignore_errors=True)

    return FixtureValidation(
        buggy_f2p_passed=buggy_f2p,
        f2p_total=f2p_total,
        buggy_p2p_passed=buggy_p2p,
        golden_f2p_passed=gold_f2p,
        golden_p2p_passed=gold_p2p,
        p2p_total=p2p_total,
        logs="\n".join(["[buggy f2p]", l1, "[buggy p2p]", l2, "[gold f2p]", l3, "[gold p2p]", l4]),
    )


def discover_task_dirs() -> list[Path]:
    dirs: list[Path] = []
    for root in (FIXTURES_ROOT, OWNED_ROOT):
        if root.is_dir():
            dirs += [d for d in sorted(root.iterdir()) if (d / "meta.yaml").is_file()]
    return dirs


def source_dir_for(instance_id: str) -> Path:
    """Locate the bundled source directory (base/test/fix) for ``instance_id``."""
    for d in discover_task_dirs():
        if _read_meta(d).get("instance_id") == instance_id:
            return d
    raise KeyError(f"no golden task directory for instance_id {instance_id!r}")


def build_dataset(*, validate: bool = True) -> list[Task]:
    """Build, validate, and write the dataset + solutions sidecar. Returns tasks."""
    tasks: list[Task] = []
    solutions: list[dict] = []
    for task_dir in discover_task_dirs():
        task, gold = build_task(task_dir)
        if validate:
            v = validate_task(task, gold, task_dir)
            if not v.is_valid:
                raise ValueError(f"{task.instance_id} failed fixture validation:\n{v.logs}")
        tasks.append(task)
        solutions.append({"instance_id": task.instance_id, "gold_patch": gold})

    tasks.sort(key=lambda t: t.instance_id)
    solutions.sort(key=lambda s: s["instance_id"])
    validate_dataset(tasks)

    DATASET_PATH.parent.mkdir(parents=True, exist_ok=True)
    DATASET_PATH.write_text("".join(t.model_dump_json() + "\n" for t in tasks))
    SOLUTIONS_PATH.write_text("".join(json.dumps(s) + "\n" for s in solutions))
    return tasks


def load_solutions(path: str | Path = SOLUTIONS_PATH) -> dict[str, str]:
    """Map instance_id -> gold_patch from the solutions sidecar."""
    out: dict[str, str] = {}
    for line in Path(path).read_text().splitlines():
        if line.strip():
            rec = json.loads(line)
            out[rec["instance_id"]] = rec["gold_patch"]
    return out


def main() -> None:
    tasks = build_dataset(validate=True)
    print(f"Built {len(tasks)} validated task(s) -> {DATASET_PATH}")
    for t in tasks:
        print(f"  {t.instance_id:32s} {t.family:14s} {t.repo}")


if __name__ == "__main__":
    main()
