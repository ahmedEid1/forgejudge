"""A solve() run emits an OTel GenAI span tree (invoke_agent > retrieval / chat /
execute_tool), gen_ai.usage.* on model spans, a gen_ai.evaluation.result event,
and returns a trace_url. Captured with an in-memory exporter (no network)."""

from pathlib import Path

import pytest
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from forgejudge.agent.solver import solve
from forgejudge.golden.build_dataset import source_dir_for
from forgejudge.golden.loader import load_tasks
from forgejudge.llm.router import Completion
from forgejudge.obs.tracing import GEN_AI_USAGE_IN, setup_tracing

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
TASKS = {t.instance_id: t for t in load_tasks(REPO_ROOT / "golden" / "dataset.jsonl")}
SEMVER = "fixture-semver-001"


def _gold_fake():
    gold = (source_dir_for(SEMVER) / "fix" / "semver.py").read_text()

    def fn(messages, *, role, run_id):
        return Completion(text=f"```python\n{gold}```", tokens_in=120, tokens_out=60,
                          cost_usd=0.0, model="groq/llama-3.3-70b-versatile")
    return fn


@pytest.mark.slow
def test_solve_emits_genai_span_tree_and_trace_url():
    mem = InMemorySpanExporter()
    setup_tracing(exporter=mem)

    res = solve(TASKS[SEMVER], run_id="trace-1", budget_usd=0.1, seed=0, max_steps=2,
                show_failing_test=True, complete_fn=_gold_fake())
    assert res.status == "ok"
    assert res.trace_url and "traces/" in res.trace_url

    spans = {s.name for s in mem.get_finished_spans()}
    assert {"invoke_agent", "retrieval", "chat", "execute_tool"} <= spans

    # gen_ai.usage.* is set on the model (chat) span.
    chat = [s for s in mem.get_finished_spans() if s.name == "chat"]
    assert any(s.attributes.get(GEN_AI_USAGE_IN) == 120 for s in chat)

    # The run carries a pass/fail evaluation verdict on the root span.
    root = next(s for s in mem.get_finished_spans() if s.name == "invoke_agent")
    evals = [e for e in root.events if e.name == "gen_ai.evaluation.result"]
    assert evals and evals[-1].attributes["gen_ai.evaluation.score.label"] == "pass"
