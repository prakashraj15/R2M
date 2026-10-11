import asyncio

import pytest

from r2m import EventKind, SpanKind


def test_nested_spans_link_parents_and_execution(client, platform):
    with client.execution("healthy") as run:
        with client.span("observe") as outer:
            with client.span("read_health", SpanKind.TOOL) as inner:
                pass
    client.flush()

    spans = {e["span_id"]: e for e in platform.events_of("span")}
    assert spans[inner.id]["parent_span_id"] == outer.id
    assert spans[outer.id]["parent_span_id"] is None
    assert spans[inner.id]["span_kind"] == "tool"
    assert all(e["execution_id"] == run.execution_id for e in platform.events.values())
    assert [e["kind"] for e in platform.events_of("execution.ended")] == ["execution.ended"]


def test_exception_marks_span_error_with_class_only(client, platform):
    with pytest.raises(ValueError):
        with client.execution():
            with client.span("boom"):
                raise ValueError("secret=hunter2 leaked")
    client.flush()
    span = platform.events_of("span")[0]
    assert span["status"] == "error"
    assert span["attributes"]["error_class"] == "ValueError"
    assert "hunter2" not in str(platform.events)
    assert platform.events_of("execution.ended")[0]["status"] == "failed"


async def test_async_spans_keep_separate_parents(client, platform):
    @client.traced("child", SpanKind.ORCHESTRATION)
    async def child(n):
        await asyncio.sleep(0.01 * n)
        return n

    async with client.execution():
        async with client.span("parent") as parent:
            await asyncio.gather(child(1), child(2))
    client.flush()
    children = [e for e in platform.events_of("span") if e["name"] == "child"]
    assert len(children) == 2
    assert {c["parent_span_id"] for c in children} == {parent.id}


def test_model_call_records_simulated_usage(client, platform):
    with client.execution():
        with client.model_call("opspilot-sim-1", purpose="diagnose") as call:
            call.record(input_tokens=1000, output_tokens=200)
    client.flush()
    usage = platform.events_of(EventKind.USAGE.value)[0]["attributes"]
    assert usage["cost_source"] == "simulated"
    assert usage["amount_usd"] == pytest.approx(0.006)
    assert platform.events_of("span")[0]["span_kind"] == "model"


def test_ingest_retries_are_idempotent(client, platform):
    platform.fail_ingest_times = 2
    with client.execution():
        client.transition(None, "RECEIVED")
    assert client.flush()
    assert platform.ingest_calls == 3
    assert len(platform.events) == 3  # started, transition, ended — no duplicates


def test_failed_batches_are_retained_not_lost(client, platform):
    platform.down = True
    with client.execution():
        client.transition(None, "RECEIVED")
    assert not client.flush()
    assert client.transport.failed_batches
    platform.down = False
    assert client.transport.retry_failed()
    assert len(platform.events) == 3


def test_redaction_of_attributes(client, platform):
    with client.execution():
        client.event(EventKind.INSIGHT, "x", {"api_key": "abc", "note": "mail bob@corp.com Bearer xyz.123",
                                              "card": "4111 1111 1111 1111"})
    client.flush()
    attrs = platform.events_of("insight")[0]["attributes"]
    assert attrs["api_key"] == "[REDACTED]"
    assert "bob@corp.com" not in attrs["note"] and "xyz.123" not in attrs["note"]
    assert attrs["card"] == "[CARD]"
