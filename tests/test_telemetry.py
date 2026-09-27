import pytest
from fastapi.testclient import TestClient
from opentelemetry import metrics, trace
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import InMemoryMetricReader
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from app import main

LOOKUP_ROUTE = "/api/orders/{order_id}"

metric_reader = InMemoryMetricReader()
metrics.set_meter_provider(MeterProvider(metric_readers=[metric_reader]))
span_exporter = InMemorySpanExporter()
tracer_provider = TracerProvider()
tracer_provider.add_span_processor(SimpleSpanProcessor(span_exporter))
trace.set_tracer_provider(tracer_provider)


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "DB_PATH", tmp_path / "orders.db")
    span_exporter.clear()
    with TestClient(main.app, raise_server_exceptions=False) as test_client:
        yield test_client


def request_count(route, status_code):
    data = metric_reader.get_metrics_data()
    total = 0
    for resource_metrics in data.resource_metrics if data else []:
        for scope_metrics in resource_metrics.scope_metrics:
            for metric in scope_metrics.metrics:
                if metric.name != "order_tracker.http.requests":
                    continue
                for point in metric.data.data_points:
                    attributes = point.attributes
                    if (attributes["http.route"], attributes["http.response.status_code"]) == (
                        route,
                        status_code,
                    ):
                        total += point.value
    return total


def test_lookup_records_route_and_status(client):
    before = request_count(LOOKUP_ROUTE, 200)
    assert client.get("/api/orders/standard-1001").status_code == 200
    assert request_count(LOOKUP_ROUTE, 200) == before + 1

    spans = {span.name: span for span in span_exporter.get_finished_spans()}
    server_span = spans[f"GET {LOOKUP_ROUTE}"]
    lookup_span = spans["order.lookup"]
    assert lookup_span.parent.span_id == server_span.context.span_id
    assert lookup_span.attributes["order.id"] == "standard-1001"


def test_missing_order_uses_route_template_not_raw_path(client):
    before = request_count(LOOKUP_ROUTE, 404)
    assert client.get("/api/orders/does-not-exist").status_code == 404
    assert request_count(LOOKUP_ROUTE, 404) == before + 1
    assert request_count("/api/orders/does-not-exist", 404) == 0


def test_unhandled_error_is_counted_as_500(client, monkeypatch):
    def broken_detail(_row):
        raise ValueError("boom")

    monkeypatch.setattr(main, "order_detail", broken_detail)
    before = request_count(LOOKUP_ROUTE, 500)
    assert client.get("/api/orders/standard-1001").status_code == 500
    assert request_count(LOOKUP_ROUTE, 500) == before + 1

    server_span = next(s for s in span_exporter.get_finished_spans() if s.name == f"GET {LOOKUP_ROUTE}")
    assert server_span.status.status_code == trace.StatusCode.ERROR


def test_unknown_path_is_grouped_as_unmatched(client):
    before = request_count("unmatched", 404)
    assert client.get("/no/such/page").status_code == 404
    assert request_count("unmatched", 404) == before + 1


def test_health_check_is_not_traced(client):
    client.get("/healthz")
    assert not [span for span in span_exporter.get_finished_spans() if "healthz" in span.name]
