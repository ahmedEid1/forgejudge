"""OpenTelemetry GenAI tracing for ForgeJudge agent runs.

Emits an ``invoke_agent`` root span with child ``retrieval`` / ``chat`` /
``execute_tool`` spans (OTel GenAI semantic conventions), ``gen_ai.usage.*`` on
model spans, and a ``gen_ai.evaluation.result`` event carrying the pass/fail
verdict. Dual export: Langfuse Cloud (curated showcase) via OTLP + an optional
self-hosted Phoenix collector (bulk). Untraced runs are cheap no-ops.

Note: ``gen_ai.usage.cost`` is *not* an OTel GenAI semantic convention (the
convention defines token counts but no cost attribute), so per-run USD cost is
recorded under the vendor-namespaced ``forgejudge.usage.cost_usd`` key to avoid
squatting on the ``gen_ai.*`` namespace.
"""

import base64
import os

from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import (
    BatchSpanProcessor,
    SimpleSpanProcessor,
    SpanExporter,
)
from opentelemetry.trace import Span

TRACER_NAME = "forgejudge"
_DEFAULT_LANGFUSE_HOST = "https://cloud.langfuse.com"

# OTel GenAI semantic-convention attribute keys.
GEN_AI_OPERATION = "gen_ai.operation.name"
GEN_AI_CONVERSATION_ID = "gen_ai.conversation.id"
GEN_AI_REQUEST_MODEL = "gen_ai.request.model"
GEN_AI_USAGE_IN = "gen_ai.usage.input_tokens"
GEN_AI_USAGE_OUT = "gen_ai.usage.output_tokens"
# ForgeJudge extension (NOT an OTel GenAI convention): per-call USD cost.
GEN_AI_USAGE_COST = "forgejudge.usage.cost_usd"
GEN_AI_TOOL_NAME = "gen_ai.tool.name"

def get_tracer() -> trace.Tracer:
    """The ForgeJudge tracer (a no-op tracer until :func:`setup_tracing`)."""
    return trace.get_tracer(TRACER_NAME)


def _langfuse_exporter() -> SpanExporter | None:
    pub = os.getenv("LANGFUSE_PUBLIC_KEY")
    sec = os.getenv("LANGFUSE_SECRET_KEY")
    if not (pub and sec):
        return None
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

    host = os.getenv("LANGFUSE_HOST", _DEFAULT_LANGFUSE_HOST).rstrip("/")
    auth = base64.b64encode(f"{pub}:{sec}".encode()).decode()
    return OTLPSpanExporter(
        endpoint=f"{host}/api/public/otel/v1/traces",
        headers={"Authorization": f"Basic {auth}"},
    )


def _phoenix_exporter() -> SpanExporter | None:
    endpoint = os.getenv("PHOENIX_OTLP_ENDPOINT")
    if not endpoint:
        return None
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

    return OTLPSpanExporter(endpoint=endpoint.rstrip("/") + "/v1/traces")


def setup_tracing(
    *, exporter: SpanExporter | None = None, service_name: str = "forgejudge"
) -> TracerProvider:
    """Install/extend the tracer provider with span exporters.

    Pass ``exporter`` to capture spans directly (e.g. an in-memory exporter in
    tests). Otherwise route to Langfuse (if keys are set) and Phoenix (if
    ``PHOENIX_OTLP_ENDPOINT`` is set). OTel forbids replacing the global
    provider once set, so we add processors to the existing SDK provider when
    there is one (creating + installing one only the first time).
    """
    provider = trace.get_tracer_provider()
    if not isinstance(provider, TracerProvider):
        provider = TracerProvider(resource=Resource.create({"service.name": service_name}))
        trace.set_tracer_provider(provider)

    if exporter is not None:
        # An explicit exporter (e.g. the in-memory test exporter) is synchronous
        # by design, so export inline for deterministic, immediate capture.
        provider.add_span_processor(SimpleSpanProcessor(exporter))
        return provider

    # Network OTLP exporters (Langfuse/Phoenix) must NOT export inline: a
    # SimpleSpanProcessor would block the agent hot path on a per-span HTTP
    # POST. Batch off-thread instead so a slow endpoint can't stall the run.
    for exp in (_langfuse_exporter(), _phoenix_exporter()):
        if exp is not None:
            provider.add_span_processor(BatchSpanProcessor(exp))
    return provider


# Memoize the resolved project id ONLY on success, keyed by the credential set.
# Caching a None/error result (as a bare @lru_cache would) freezes the wrong,
# project-less fallback URL for the whole process even after keys/connectivity
# recover; so failures are never cached and the next call retries.
_PROJECT_ID_CACHE: dict[tuple[str, str], str] = {}


def _reset_project_id_cache() -> None:
    """Clear the project-id memo (used by tests across env changes)."""
    _PROJECT_ID_CACHE.clear()


def _fetch_langfuse_project_id() -> str | None:
    """Resolve the Langfuse project id from the API (no caching)."""
    pub = os.getenv("LANGFUSE_PUBLIC_KEY")
    sec = os.getenv("LANGFUSE_SECRET_KEY")
    if not (pub and sec):
        return None
    try:
        import urllib.request

        host = os.getenv("LANGFUSE_HOST", _DEFAULT_LANGFUSE_HOST).rstrip("/")
        auth = base64.b64encode(f"{pub}:{sec}".encode()).decode()
        req = urllib.request.Request(  # noqa: S310 - fixed https host
            f"{host}/api/public/projects", headers={"Authorization": f"Basic {auth}"}
        )
        import json

        with urllib.request.urlopen(req, timeout=10) as resp:  # noqa: S310
            data = json.load(resp)
        projects = data.get("data", [])
        return projects[0]["id"] if projects else None
    except Exception:  # noqa: BLE001 - URL is best-effort
        return None


def _langfuse_project_id() -> str | None:
    pub = os.getenv("LANGFUSE_PUBLIC_KEY")
    sec = os.getenv("LANGFUSE_SECRET_KEY")
    if not (pub and sec):
        return None
    key = (pub, sec)
    cached = _PROJECT_ID_CACHE.get(key)
    if cached is not None:
        return cached
    project_id = _fetch_langfuse_project_id()
    if project_id is not None:
        _PROJECT_ID_CACHE[key] = project_id
    return project_id


def trace_url_for(span: Span) -> str:
    """Best-effort Langfuse deep link for ``span``'s trace.

    Returns "" when the span is untraced (no-op span, ``trace_id == 0``) *or*
    when Langfuse is not the configured exporter. The latter guard matters
    because a real TracerProvider gives every span a non-zero ``trace_id`` even
    on Phoenix-only / local / CI / in-memory-test runs; without it we would
    advertise a ``cloud.langfuse.com`` deep link to a trace that was never sent
    there (a guaranteed dead 404 link on a public showcase record).
    """
    ctx = span.get_span_context()
    if not ctx or not ctx.trace_id:
        return ""
    # Only emit a Langfuse URL when Langfuse export is actually configured.
    if not (os.getenv("LANGFUSE_PUBLIC_KEY") and os.getenv("LANGFUSE_SECRET_KEY")):
        return ""
    trace_id = format(ctx.trace_id, "032x")
    host = os.getenv("LANGFUSE_HOST", _DEFAULT_LANGFUSE_HOST).rstrip("/")
    project_id = _langfuse_project_id()
    if project_id:
        return f"{host}/project/{project_id}/traces/{trace_id}"
    return f"{host}/traces/{trace_id}"


def record_evaluation(
    span: Span, *, name: str, value: float, label: str, explanation: str = ""
) -> None:
    """Attach a ``gen_ai.evaluation.result`` event (golden-eval verdict) to ``span``."""
    span.add_event(
        "gen_ai.evaluation.result",
        attributes={
            "gen_ai.evaluation.name": name,
            "gen_ai.evaluation.score.value": value,
            "gen_ai.evaluation.score.label": label,
            "gen_ai.evaluation.explanation": explanation,
        },
    )


def set_model_usage(span: Span, *, model: str, tokens_in: int, tokens_out: int, cost: float) -> None:
    span.set_attribute(GEN_AI_REQUEST_MODEL, model)
    span.set_attribute(GEN_AI_USAGE_IN, tokens_in)
    span.set_attribute(GEN_AI_USAGE_OUT, tokens_out)
    # Cost is a ForgeJudge extension, not an OTel GenAI attribute. Only record it
    # when it is actually known: a literal 0.0 (free models, fixtures) is
    # indistinguishable from "unknown" and would skew cost dashboards.
    if cost:
        span.set_attribute(GEN_AI_USAGE_COST, cost)
