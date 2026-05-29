"""Single-agent, phase-structured solve loop: localize -> repair -> validate.

Roles are sequential STAGES of one deterministic loop (Agentless-style), not
concurrent sub-agents. Reliability levers: test-execution feedback (the loop
re-runs the tests and feeds failures back), a syntax edit-gate (a syntactically
broken edit is reverted, never submitted), and a cost/step budget with
autosubmit (return the best diff so far when the budget is spent).
"""

import shutil
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from forgejudge.agent.critic import CritiqueResult, critique
from forgejudge.agent.localize import _is_test_file, localize
from forgejudge.agent.repair import build_edit_messages, extract_code, is_valid_python
from forgejudge.golden.build_dataset import source_dir_for
from forgejudge.golden.materialize import (
    apply_unified_diff,
    copy_tree,
    git,
    init_base_repo,
    run_nodeids_status,
    staged_diff_against_base,
)
from forgejudge.llm.router import Completion, complete
from forgejudge.obs.tracing import (
    GEN_AI_CONVERSATION_ID,
    GEN_AI_OPERATION,
    GEN_AI_TOOL_NAME,
    get_tracer,
    record_evaluation,
    set_model_usage,
    trace_url_for,
)
from forgejudge.types import Task

CompleteFn = Callable[..., Completion]

_TEST_RE = ("test_", "_test.py")


@dataclass
class SolveResult:
    patch: str                              # unified diff (source only) the agent produced
    status: Literal["ok", "budget_exceeded", "error"]
    steps: int
    cost_usd: float
    resolved_in_loop: bool                  # the agent's own validation passed
    reverted_edits: int = 0                 # edits the syntax gate rejected
    critic_rejections: int = 0              # edits the critic rejected before testing
    no_code_responses: int = 0              # steps where the model emitted no usable code block
    trace_url: str = ""                     # deep link into the run's Langfuse trace
    tokens_in: int = 0
    tokens_out: int = 0


def _is_test_path(rel: str) -> bool:
    # Reuse the localizer's predicate so the fallback target and the localizer
    # never disagree about which files are tests (vs. editable source).
    return _is_test_file(Path(rel))


def _fallback_target(work: Path) -> str | None:
    for p in sorted(work.rglob("*.py")):
        rel = p.relative_to(work).as_posix()
        if ".git" not in rel and not _is_test_path(rel):
            return rel
    return None


def _no_regression(status: dict[str, bool]) -> bool:
    """No PASS_TO_PASS test regressed: vacuously true when there are none to run."""
    return all(status.values())


def _read_failing_tests(work: Path, task: Task) -> str:
    paths = dict.fromkeys(nid.split("::", 1)[0] for nid in task.fail_to_pass)
    chunks = []
    for rel in paths:
        fp = work / rel
        if fp.exists():
            chunks.append(f"# {rel}\n{fp.read_text()}")
    return "\n\n".join(chunks)


def _all_pass(status: dict[str, bool]) -> bool:
    return bool(status) and all(status.values())


def solve(
    task: Task,
    *,
    run_id: str,
    budget_usd: float = 0.10,
    seed: int = 0,
    max_steps: int = 6,
    complete_fn: CompleteFn | None = None,
    critic_fn: CompleteFn | None = None,
    source_dir: str | Path | None = None,
    show_failing_test: bool = False,
) -> SolveResult:
    """Produce a candidate unified-diff patch for ``task``.

    Two modes:

    * ``show_failing_test=False`` (default, the credible benchmark): the agent
      sees only the issue text + the buggy code (base, with its existing
      PASS_TO_PASS tests) — the FAIL_TO_PASS test is HIDDEN, applied only at
      grading. It fixes from the issue and validates against no-regression. This
      is the real SWE-bench setup; resolution is decided by the hidden oracle.
    * ``show_failing_test=True``: the failing test is materialised and shown
      (test-driven repair). Easier; useful for harness tests / demos.

    The agent may edit only source; tests are restored at grading time.
    """
    complete_fn = complete_fn or complete
    src = Path(source_dir) if source_dir is not None else source_dir_for(task.instance_id)
    tracer = get_tracer()

    work = Path(tempfile.mkdtemp(prefix=f"fjsolve-{task.instance_id}-"))
    steps = 0
    cost = 0.0
    tok_in = 0
    tok_out = 0
    reverted = 0
    critic_rejections = 0
    no_code = 0
    status: str = "budget_exceeded"
    patch = ""

    def _critique(code: str) -> CritiqueResult:
        """Run the critic, folding its (otherwise-uncounted) spend into the totals."""
        nonlocal cost, tok_in, tok_out
        captured: list[Completion] = []

        def _tap(messages, **kwargs):
            comp = critic_fn(messages, **kwargs)
            captured.append(comp)
            return comp

        verdict = critique(task, code, failing_tests, complete_fn=_tap, run_id=run_id)
        for comp in captured:
            cost += comp.cost_usd
            tok_in += comp.tokens_in
            tok_out += comp.tokens_out
        return verdict
    with tracer.start_as_current_span("invoke_agent") as root:
        root.set_attribute(GEN_AI_OPERATION, "invoke_agent")
        root.set_attribute(GEN_AI_CONVERSATION_ID, run_id)
        root.set_attribute("forgejudge.task_id", task.instance_id)
        root.set_attribute("forgejudge.seed", seed)
        trace_url = trace_url_for(root)
        try:
            copy_tree(src / "base", work)
            init_base_repo(work)
            if show_failing_test:
                apply_unified_diff(work, task.test_patch)
                git(work, "add", "-A")
                git(work, "commit", "-q", "-m", "base+test")

            with tracer.start_as_current_span("retrieval") as rsp:
                rsp.set_attribute(GEN_AI_OPERATION, "retrieval")
                ranked = localize(task, work, top_k=3)
                target = ranked[0] if ranked else _fallback_target(work)
                rsp.set_attribute("forgejudge.localized", target or "")
            if target is None:
                record_evaluation(root, name="resolved", value=0.0, label="fail",
                                  explanation="no source file to edit")
                return SolveResult("", "error", 0, 0.0, False, 0, 0, 0, trace_url)

            failing_tests = _read_failing_tests(work, task) if show_failing_test else ""
            feedback = ""
            for _ in range(max_steps):
                if cost >= budget_usd > 0:
                    break
                target_src = (work / target).read_text()
                messages = build_edit_messages(task, target, target_src, failing_tests, feedback)
                with tracer.start_as_current_span("chat") as csp:
                    csp.set_attribute(GEN_AI_OPERATION, "chat")
                    comp = complete_fn(messages, role="edit", run_id=run_id, seed=seed)
                    set_model_usage(csp, model=comp.model, tokens_in=comp.tokens_in,
                                    tokens_out=comp.tokens_out, cost=comp.cost_usd)
                steps += 1
                cost += comp.cost_usd
                tok_in += comp.tokens_in
                tok_out += comp.tokens_out

                code = extract_code(comp.text)
                if code is None:
                    no_code += 1
                    feedback = f"Return the complete contents of {target} in one ```python block."
                    continue
                if not is_valid_python(code):
                    reverted += 1
                    feedback = "Your edit was not valid Python (syntax error). Return a valid file."
                    continue

                # Cheap critic filter before the (expensive) test run.
                if critic_fn is not None:
                    with tracer.start_as_current_span("chat") as ksp:
                        ksp.set_attribute(GEN_AI_OPERATION, "chat")
                        ksp.set_attribute("forgejudge.role", "critic")
                        verdict = _critique(code)
                    if not verdict.approved:
                        critic_rejections += 1
                        feedback = f"A reviewer rejected the edit: {verdict.reason}"
                        continue

                (work / target).write_text(code)
                with tracer.start_as_current_span("execute_tool") as tsp:
                    tsp.set_attribute(GEN_AI_TOOL_NAME, "pytest")
                    p2p, _ = run_nodeids_status(work, task.pass_to_pass)
                    # The FAIL_TO_PASS test only exists in the tree when visible.
                    f2p = run_nodeids_status(work, task.fail_to_pass)[0] if show_failing_test else {}

                if show_failing_test:
                    if _all_pass(f2p) and _all_pass(p2p):
                        status = "ok"
                        break
                    failed = [n for n, ok in {**f2p, **p2p}.items() if not ok]
                    feedback = "These tests still fail: " + ", ".join(failed)
                else:
                    # Hidden test: accept the first issue-guided edit that keeps the
                    # existing tests green (no regression); the hidden oracle decides.
                    # A task whose buggy base has no PASS_TO_PASS tests has nothing to
                    # regress, so "no regression" is vacuously satisfied — otherwise the
                    # success gate would be structurally unreachable for such tasks.
                    if _no_regression(p2p):
                        status = "ok"
                        break
                    failed = [n for n, ok in p2p.items() if not ok]
                    feedback = "Your change broke existing tests: " + ", ".join(failed)
                git(work, "checkout", "HEAD", "--", target)  # retry from clean base

            patch = staged_diff_against_base(work)
            record_evaluation(
                root, name="resolved",
                value=1.0 if status == "ok" else 0.0,
                label="pass" if status == "ok" else "fail",
                explanation=f"status={status}, steps={steps}",
            )
        except Exception:  # noqa: BLE001 - any failure is reported as an errored run
            root.set_attribute("forgejudge.error", True)
            return SolveResult("", "error", steps, cost, False, reverted, critic_rejections,
                               no_code, trace_url, tok_in, tok_out)
        finally:
            shutil.rmtree(work, ignore_errors=True)

    # In hidden mode the agent cannot confirm a fix (the oracle is hidden), so
    # resolved_in_loop is only meaningful when the failing test was shown.
    resolved_in_loop = show_failing_test and status == "ok"
    return SolveResult(patch, status, steps, cost, resolved_in_loop, reverted, critic_rejections,
                       no_code, trace_url, tok_in, tok_out)
