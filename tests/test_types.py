"""Contract tests for the canonical ForgeJudge data models."""

import pytest

from forgejudge.types import GradeResult, RunRecord, Task


def _make_task() -> Task:
    return Task(
        instance_id="fixture-jsonpath-001",
        family="make_ci_green",
        repo="fixture:jsonpath",
        base_commit="",
        problem_statement="`get('$.a.b')` raises KeyError instead of returning None.",
        test_patch="--- a/test_x.py\n+++ b/test_x.py\n@@\n+def test_missing(): ...\n",
        fail_to_pass=["test_x.py::test_missing"],
        pass_to_pass=["test_x.py::test_present"],
        env_image="forgejudge/jsonpath:001",
        source_license="own",
        created_at="2026-05-29",
    )


def test_task_round_trip():
    task = _make_task()
    restored = Task.model_validate_json(task.model_dump_json())
    assert restored == task
    assert restored.language == "python"  # default applied


def test_run_record_round_trip():
    grade = GradeResult(f2p_passed=1, f2p_total=1, p2p_passed=1, p2p_total=1, logs="ok")
    record = RunRecord(
        run_id="run-abc",
        task_id="fixture-jsonpath-001",
        model="groq/llama-3.3-70b-versatile",
        scaffold_version="0.1.0",
        seed=0,
        resolved=grade.resolved,
        grade=grade,
        patch="--- a/x.py\n+++ b/x.py\n",
        tokens_in=1200,
        tokens_out=300,
        cost_usd=0.0,
        wall_clock_s=4.2,
        trace_url="https://cloud.langfuse.com/trace/abc",
        status="ok",
        created_at="2026-05-29T12:00:00Z",
    )
    restored = RunRecord.model_validate_json(record.model_dump_json())
    assert restored == record
    assert restored.judge_score is None  # optional default


@pytest.mark.parametrize(
    ("f2p_p", "f2p_t", "p2p_p", "p2p_t", "expected"),
    [
        (1, 1, 1, 1, True),   # all transitions satisfied
        (0, 1, 1, 1, False),  # a FAIL_TO_PASS test did not pass
        (1, 1, 0, 1, False),  # a PASS_TO_PASS test regressed
        (0, 0, 0, 0, True),   # vacuously satisfied (both ratios 1.0)
    ],
)
def test_grade_resolved_is_derived_from_counts(f2p_p, f2p_t, p2p_p, p2p_t, expected):
    grade = GradeResult(
        f2p_passed=f2p_p, f2p_total=f2p_t, p2p_passed=p2p_p, p2p_total=p2p_t, logs=""
    )
    assert grade.resolved is expected
    # The invariant must survive serialization.
    assert GradeResult.model_validate_json(grade.model_dump_json()).resolved is expected
