"""OpenTelemetry GenAI tracing for ForgeJudge agent runs.

Emits an ``invoke_agent`` root span with child ``retrieval`` / ``chat`` /
``execute_tool`` spans (OTel GenAI semantic conventions), ``gen_ai.usage.*`` on
model spans, and a ``gen_ai.evaluation.result`` event carrying the pass/fail
verdict. Dual export: Langfuse Cloud (curated showcase) via OTLP + an optional
self-hosted Phoenix collector (bulk). Untraced runs are cheap no-ops.
"""

import base64
import os
from functools import lru_cache

from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor, SpanExporter
from opentelemetry.trace import Span

TRACER_NAME = "forgejudge"
_DEFAULT_LANGFUSE_HOST = "https://cloud.langfuse.com"

# OTel GenAI semantic-convention attribute keys.
GEN_AI_OPERATION = "gen_ai.operation.name"
GEN_AI_CONVERSATION_ID = "gen_ai.conversation.id"
GEN_AI_REQUEST_MODEL = "gen_ai.request.model"
GEN_AI_USAGE_IN = "gen_ai.usage.input_tokens"
GEN_AI_USAGE_OUT = "gen_ai.usage.output_tokens"
GEN_AI_USAGE_COST = "gen_ai.usage.cost"
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

    exporters = [exporter] if exporter is not None else [
        e for e in (_langfuse_exporter(), _phoenix_exporter()) if e is not None
    ]
    for exp in exporters:
        provider.add_span_processor(SimpleSpanProcessor(exp))
    return provider


@lru_cache(maxsize=1)
def _langfuse_project_id() -> str | None:
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


def trace_url_for(span: Span) -> str:
    """Best-effort Langfuse deep link for ``span``'s trace; "" if untraced."""
    ctx = span.get_span_context()
    if not ctx or not ctx.trace_id:
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
    span.set_attribute(GEN_AI_USAGE_COST, cost)
