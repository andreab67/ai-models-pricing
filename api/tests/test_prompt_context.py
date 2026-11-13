"""Extractor provenance records actual source bytes without changing pricing authority."""

import hashlib
import json

import httpx
import pytest

from app.services import kilo_extract


def native_exporter(monkeypatch):
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import SimpleSpanProcessor
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

    from app import observability

    exporter = InMemorySpanExporter()
    provider = TracerProvider(shutdown_on_exit=False)
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    monkeypatch.setattr(observability, "_runtime", (provider, provider.get_tracer("test")))
    monkeypatch.setattr(observability, "_initialized", True)
    return provider, exporter


async def test_snapshot_precedes_client_entry_and_matches_exact_wire(monkeypatch):
    provider, exporter = native_exporter(monkeypatch)
    monkeypatch.setenv("LANGFUSE_PROJECT_ID", "pricing-project")
    original = kilo_extract._SYSTEM_PROMPT
    schema = json.dumps(
        kilo_extract.KiloPricePrimitives.model_json_schema(), sort_keys=True, separators=(",", ":")
    )
    sent = []
    primitives = {
        "tiers": [
            {"tier": tier, "monthly_usd": 10, "max_credits_usd": 14}
            for tier in ("starter", "pro", "expert")
        ],
        "annual_bonus_pct": 0.5,
    }

    def handler(request):
        sent.append(json.loads(request.content))
        return httpx.Response(
            200, json={"choices": [{"message": {"content": json.dumps(primitives)}}]}
        )

    actual_client = httpx.AsyncClient

    class Client:
        def __init__(self, **kwargs):
            self.inner = actual_client(transport=httpx.MockTransport(handler), **kwargs)

        async def __aenter__(self):
            monkeypatch.setattr(kilo_extract, "_SYSTEM_PROMPT", "mutated during await")
            monkeypatch.setenv("LANGFUSE_PROJECT_ID", "other-project")
            return await self.inner.__aenter__()

        async def __aexit__(self, *args):
            return await self.inner.__aexit__(*args)

    monkeypatch.setattr(kilo_extract.httpx, "AsyncClient", Client)
    result = await kilo_extract.extract_pricing("private page fixture")
    assert len(result.plans) == 3
    assert all(plan.annual_usd == 120 for plan in result.plans)
    assert sent[0]["messages"][0]["content"] == original
    assert sent[0]["response_format"] == {"type": "json_object"}
    assert not {"temperature", "top_p", "top_k"} & sent[0].keys()
    (span,) = exporter.get_finished_spans()
    attrs = dict(span.attributes)
    metadata = json.loads(attrs["langfuse.observation.metadata.context_provenance"])
    assert metadata["project_id"] == "pricing-project"
    components = metadata["prompts"][0]["components"]
    assert components["system"] == hashlib.sha256(original.encode()).hexdigest()
    assert components["local_validation_schema"] == hashlib.sha256(schema.encode()).hexdigest()
    assert attrs["langfuse.observation.type"] == "generation"
    assert "private page fixture" not in json.dumps(attrs)
    assert "langfuse.observation.input" not in attrs
    assert "langfuse.observation.output" not in attrs
    provider.shutdown()


async def test_failure_preserves_original_exception_without_exporting_page(monkeypatch):
    provider, exporter = native_exporter(monkeypatch)
    failure = httpx.ConnectError("private page fixture")

    async def post(*args, **kwargs):
        raise failure

    monkeypatch.setattr(httpx.AsyncClient, "post", post)
    with pytest.raises(httpx.ConnectError) as caught:
        await kilo_extract.extract_pricing("private page fixture")
    assert caught.value is failure
    (span,) = exporter.get_finished_spans()
    assert span.attributes["langfuse.observation.status_message"] == "ConnectError"
    assert not span.events
    assert "private page fixture" not in json.dumps(dict(span.attributes))
    provider.shutdown()
