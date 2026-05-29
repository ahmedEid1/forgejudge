"""Canonical ForgeJudge data contracts (Pydantic v2).

Defined ONCE here; every module imports its models from this file. See the
implementation plan's "Shared contracts" section — these signatures are pinned.
"""

from typing import Literal

from pydantic import BaseModel, computed_field

TaskFamily = Literal["make_ci_green", "raise_coverage"]


class Task(BaseModel):
    """A single intrinsically-verifiable coding task."""

    instance_id: str                 # e.g. "fixture-jsonpath-001"
    family: TaskFamily
    repo: str                        # "fixture:<name>" | "ahmedEid1/<repo>"
    base_commit: str                 # SHA, or "" for fixtures pinned by tag
    problem_statement: str           # issue text, scrubbed of any fix leak
    test_patch: str                  # unified diff that introduces the failing test(s)
    fail_to_pass: list[str]          # test node ids that must go FAIL->PASS
    pass_to_pass: list[str]          # test node ids that must stay PASS
    env_image: str                   # pinned docker image tag
    language: Literal["python"] = "python"
    source_license: str              # "MIT" | "Apache-2.0" | "own"
    created_at: str                  # ISO date; must be post model-cutoff


class GradeResult(BaseModel):
    """The deterministic verdict for one patch against one task.

    ``resolved`` is *derived* from the counts (the official SWE-bench rule:
    ``FULL`` only when both the FAIL_TO_PASS and PASS_TO_PASS ratios are 1.0),
    so it can never disagree with the underlying test transitions.
    """

    f2p_passed: int
    f2p_total: int
    p2p_passed: int
    p2p_total: int
    logs: str

    @computed_field  # type: ignore[prop-decorator]
    @property
    def resolved(self) -> bool:
        return self.f2p_passed == self.f2p_total and self.p2p_passed == self.p2p_total


class RunRecord(BaseModel):
    """One agent run on one task: the row persisted to the run store."""

    run_id: str
    task_id: str
    model: str
    scaffold_version: str
    seed: int
    resolved: bool
    grade: GradeResult
    patch: str                       # unified diff the agent produced
    tokens_in: int
    tokens_out: int
    cost_usd: float
    wall_clock_s: float
    trace_url: str                   # deep link into Langfuse
    judge_score: float | None = None
    status: Literal["ok", "error", "timeout", "budget_exceeded"]
    created_at: str
