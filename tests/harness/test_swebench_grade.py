"""ForgeJudge's deterministic verdict must agree with the official swebench
grading rule. Requires the optional ``forgejudge[harness]`` extra (swebench)."""

import shutil
import tempfile
from pathlib import Path

import pytest

pytest.importorskip("swebench")

from forgejudge.golden.build_dataset import load_solutions, source_dir_for  # noqa: E402
from forgejudge.golden.loader import load_tasks  # noqa: E402
from forgejudge.golden.materialize import (  # noqa: E402
    copy_tree,
    init_base_repo,
    staged_diff_against_base,
)
from forgejudge.harness.runner_local import run_task_patch  # noqa: E402
from forgejudge.harness.swebench_grade import is_resolved_by_swebench  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
TASKS = {t.instance_id: t for t in load_tasks(REPO_ROOT / "golden" / "dataset.jsonl")}
GOLD = load_solutions(REPO_ROOT / "golden" / "solutions.jsonl")
SEMVER = "fixture-semver-001"

pytestmark = [pytest.mark.slow, pytest.mark.swebench]


def _break_p2p_patch() -> str:
    tmp = Path(tempfile.mkdtemp(prefix="fjswe-"))
    try:
        copy_tree(source_dir_for(SEMVER) / "base", tmp)
        init_base_repo(tmp)
        (tmp / "semver.py").write_text("def compare(a, b):\n    return 0\n")
        return staged_diff_against_base(tmp)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


@pytest.mark.parametrize(
    ("patch_fn", "expected_resolved"),
    [
        (lambda: GOLD[SEMVER], True),
        (lambda: "", False),
        (_break_p2p_patch, False),
    ],
)
def test_our_verdict_matches_official_swebench(patch_fn, expected_resolved):
    task = TASKS[SEMVER]
    outcome = run_task_patch(task, patch_fn(), source_dir_for(SEMVER))
    ours = (
        outcome.f2p_passed == outcome.f2p_total
        and outcome.p2p_passed == outcome.p2p_total
    )
    official = is_resolved_by_swebench(task, outcome.status_map)
    assert ours == official == expected_resolved
