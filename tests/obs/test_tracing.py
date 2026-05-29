"""A solve() run emits an OTel GenAI span tree (invoke_agent > retrieval / chat /
execute_tool), gen_ai.usage.* on model spans, a gen_ai.evaluation.result event,
and returns a trace_url. Captured with an in-memory exporter (no network).

Also covers the observability invariants directly on forgejudge.obs.tracing:
trace links only point at Langfuse when Langfuse is actually configured, the
project-id lookup never caches a failure, network OTLP export is batched (not
synchronous-per-span), and cost is a vendor-namespaced attribute set only when
known.
"""

from pathlib import Path

import pytest
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

import forgejudge.obs.tracing as tracing
from forgejudge.agent.solver import solve
from forgejudge.golden.build_dataset import source_dir_for
from forgejudge.golden.loader import load_tasks
from forgejudge.llm.router import Completion
from forgejudge.obs.tracing import (
    GEN_AI_USAGE_COST,
    GEN_AI_USAGE_IN,
    set_model_usage,
    setup_tracing,
    trace_url_for,
)

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
TASKS = {t.instance_id: t for t in load_tasks(REPO_ROOT / "golden" / "dataset.jsonl")}
SEMVER = "fixture-semver-001"

_LANGFUSE_ENV = (
    "LANGFUSE_PUBLIC_KEY",
    "LANGFUSE_SECRET_KEY",
    "LANGFUSE_HOST",
    "PHOENIX_OTLP_ENDPOINT",
)


@pytest.fixture
def clean_tracing_env(monkeypatch):
    """Drop all tracing-related env vars and reset the project-id memo."""
    for var in _LANGFUSE_ENV:
        monkeypatch.delenv(var, raising=False)
    tracing._reset_project_id_cache()
    yield monkeypatch
    tracing._reset_project_id_cache()


def _real_span() -> object:
    """A real (non-no-op) span with a non-zero trace_id, captured in memory."""
    prov = TracerProvider()
    mem = InMemorySpanExporter()
    prov.add_span_processor(SimpleSpanProcessor(mem))
    tracer = prov.get_tracer("forgejudge-test")
    span = tracer.start_span("invoke_agent")
    assert span.get_span_context().trace_id != 0
    return span


def _gold_fake():
    gold = (source_dir_for(SEMVER) / "fix" / "semver.py").read_text()

    def fn(messages, *, role, run_id, **_):
        return Completion(text=f"```python\n{gold}```", tokens_in=120, tokens_out=60,
                          cost_usd=0.0, model="groq/llama-3.3-70b-versatile")
    return fn


@pytest.mark.slow
def test_solve_emits_genai_span_tree_and_trace_url(clean_tracing_env):
    # clean_tracing_env drops LANGFUSE_*/PHOENIX_* so this run is fully local:
    # the in-memory exporter captures spans and no network call is made.
    mem = InMemorySpanExporter()
    setup_tracing(exporter=mem)

    res = solve(TASKS[SEMVER], run_id="trace-1", budget_usd=0.1, seed=0, max_steps=2,
                show_failing_test=True, complete_fn=_gold_fake())
    assert res.status == "ok"
    # Langfuse is not configured for this run, so there is no live trace to
    # deep-link to: the showcase URL must be empty rather than a dead link.
    assert res.trace_url == ""

    spans = {s.name for s in mem.get_finished_spans()}
    assert {"invoke_agent", "retrieval", "chat", "execute_tool"} <= spans

    # gen_ai.usage.* is set on the model (chat) span.
    chat = [s for s in mem.get_finished_spans() if s.name == "chat"]
    assert any(s.attributes.get(GEN_AI_USAGE_IN) == 120 for s in chat)

    # The run carries a pass/fail evaluation verdict on the root span.
    root = next(s for s in mem.get_finished_spans() if s.name == "invoke_agent")
    evals = [e for e in root.events if e.name == "gen_ai.evaluation.result"]
    assert evals and evals[-1].attributes["gen_ai.evaluation.score.label"] == "pass"


# --- Finding #25: no dead cloud.langfuse.com link when Langfuse isn't exporting --

def test_trace_url_empty_when_langfuse_not_configured(clean_tracing_env):
    span = _real_span()
    try:
        url = trace_url_for(span)
    finally:
        span.end()
    assert url == "", f"expected no link without Langfuse keys, got {url!r}"
    assert "langfuse.com" not in url


def test_trace_url_langfuse_when_keys_present(clean_tracing_env, monkeypatch):
    clean_tracing_env.setenv("LANGFUSE_PUBLIC_KEY", "pk-fake")
    clean_tracing_env.setenv("LANGFUSE_SECRET_KEY", "sk-fake")
    clean_tracing_env.setenv("LANGFUSE_HOST", "https://cloud.langfuse.com")
    # Avoid any real network call to resolve the project id.
    monkeypatch.setattr(tracing, "_fetch_langfuse_project_id", lambda: "proj-abc")
    span = _real_span()
    try:
        url = trace_url_for(span)
    finally:
        span.end()
    assert url == f"https://cloud.langfuse.com/project/proj-abc/traces/{format(span.get_span_context().trace_id, '032x')}"  # noqa: E501
    assert "/traces/" in url


def test_trace_url_empty_for_untraced_span(clean_tracing_env):
    # A no-op span (no provider installed) has trace_id == 0.
    from opentelemetry.trace import NonRecordingSpan, SpanContext, TraceFlags

    noop = NonRecordingSpan(SpanContext(0, 0, is_remote=False, trace_flags=TraceFlags(0)))
    assert trace_url_for(noop) == ""


# --- Finding #26: project-id lookup must not cache a failure across env changes --

def test_project_id_does_not_cache_failure(clean_tracing_env, monkeypatch):
    # First call: no keys -> None, and that must NOT be cached.
    assert tracing._langfuse_project_id() is None

    calls = {"n": 0}

    def fake_fetch():
        calls["n"] += 1
        return "proj-123"

    monkeypatch.setattr(tracing, "_fetch_langfuse_project_id", fake_fetch)
    clean_tracing_env.setenv("LANGFUSE_PUBLIC_KEY", "pk-fake")
    clean_tracing_env.setenv("LANGFUSE_SECRET_KEY", "sk-fake")

    # The earlier None must not be frozen in a cache: this must re-resolve.
    assert tracing._langfuse_project_id() == "proj-123"
    # And a successful id IS memoized (no second network fetch).
    assert tracing._langfuse_project_id() == "proj-123"
    assert calls["n"] == 1


# --- Finding #27: network OTLP export must use BatchSpanProcessor ----------------

def test_network_exporters_use_batch_processor(clean_tracing_env, monkeypatch):
    clean_tracing_env.setenv("LANGFUSE_PUBLIC_KEY", "pk-fake")
    clean_tracing_env.setenv("LANGFUSE_SECRET_KEY", "sk-fake")
    clean_tracing_env.setenv("PHOENIX_OTLP_ENDPOINT", "http://localhost:6006")

    added = []
    real_add = TracerProvider.add_span_processor

    def spy(self, proc):
        added.append(proc)
        return real_add(self, proc)

    monkeypatch.setattr(TracerProvider, "add_span_processor", spy)
    # Force a fresh provider so processors are actually added on this call.
    from opentelemetry import trace

    monkeypatch.setattr(trace, "_TRACER_PROVIDER", None, raising=False)
    setup_tracing()

    assert added, "no span processors were installed for network exporters"
    assert all(isinstance(p, BatchSpanProcessor) for p in added), (
        f"network OTLP exporters must be batched, got {[type(p).__name__ for p in added]}"
    )


def test_explicit_exporter_uses_simple_processor(clean_tracing_env, monkeypatch):
    mem = InMemorySpanExporter()
    added = []
    real_add = TracerProvider.add_span_processor

    def spy(self, proc):
        added.append(proc)
        return real_add(self, proc)

    monkeypatch.setattr(TracerProvider, "add_span_processor", spy)
    from opentelemetry import trace

    monkeypatch.setattr(trace, "_TRACER_PROVIDER", None, raising=False)
    setup_tracing(exporter=mem)

    assert added and all(isinstance(p, SimpleSpanProcessor) for p in added)


# --- Finding #37: cost is vendor-namespaced and set only when known --------------

def test_cost_key_is_not_in_genai_namespace():
    assert not GEN_AI_USAGE_COST.startswith("gen_ai."), (
        f"cost is a ForgeJudge extension and must not squat on gen_ai.*: {GEN_AI_USAGE_COST}"
    )


def test_cost_not_recorded_when_zero():
    span = _real_span()
    try:
        set_model_usage(span, model="m", tokens_in=10, tokens_out=5, cost=0.0)
        attrs = span.attributes
    finally:
        span.end()
    assert GEN_AI_USAGE_COST not in attrs, "zero/unknown cost must not be recorded"
    assert attrs[GEN_AI_USAGE_IN] == 10


def test_cost_recorded_when_positive():
    span = _real_span()
    try:
        set_model_usage(span, model="m", tokens_in=10, tokens_out=5, cost=0.0123)
        attrs = span.attributes
    finally:
        span.end()
    assert attrs[GEN_AI_USAGE_COST] == pytest.approx(0.0123)
