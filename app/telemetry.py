"""OpenTelemetry metrics, traces, and logs for Order Tracker.

TELEMETRY_EXPORTER selects where the signals go:

- ``console`` (default): print them to stdout, one JSON object per line,
  so they show up in ``docker compose logs app``.
- ``otlp``: send them to an OpenTelemetry Collector at
  ``OTEL_EXPORTER_OTLP_ENDPOINT`` (standard OTel variable).
- ``none``: install nothing; tests set up their own in-memory providers.

Metrics carry only low-cardinality attributes: route template (never the raw
path), method, and status code. Spans and logs add the concrete path and the
order id/priority.
Customer names, items, headers, and request bodies are never exported.
"""

import logging
import os
import time

from fastapi import FastAPI, Request
from opentelemetry import metrics, propagate, trace
from opentelemetry._logs import set_logger_provider
from opentelemetry.instrumentation.logging.handler import LoggingHandler
from opentelemetry.sdk._logs import LoggerProvider
from opentelemetry.sdk._logs.export import BatchLogRecordProcessor, ConsoleLogRecordExporter
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import ConsoleMetricExporter, PeriodicExportingMetricReader
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter
from opentelemetry.trace import SpanKind, Status, StatusCode


SERVICE_NAME = "order-tracker"
EXPORTERS = {"console", "otlp", "none"}
DEFAULT_METRIC_EXPORT_INTERVAL_MS = 5000
UNTRACED_PATHS = {"/healthz"}
UNMATCHED_ROUTE = "unmatched"

tracer = trace.get_tracer("order_tracker")
meter = metrics.get_meter("order_tracker")
logger = logging.getLogger("order_tracker")

request_counter = meter.create_counter(
    "order_tracker.http.requests",
    unit="{request}",
    description="HTTP requests handled, by route and status code",
)
request_duration = meter.create_histogram(
    "order_tracker.http.request.duration",
    unit="s",
    description="HTTP request duration, by route and status code",
)


def one_line_json(signal) -> str:
    return signal.to_json(indent=None) + os.linesep


def build_resource() -> Resource:
    return Resource.create(
        {
            "service.name": SERVICE_NAME,
            "service.version": os.getenv("ORDER_TRACKER_VERSION", "dev"),
            "deployment.environment.name": os.getenv("DEPLOYMENT_ENVIRONMENT", "local"),
        }
    )


def build_exporters(exporter: str):
    if exporter == "console":
        return (
            ConsoleSpanExporter(formatter=one_line_json),
            ConsoleMetricExporter(formatter=one_line_json),
            ConsoleLogRecordExporter(formatter=one_line_json),
        )
    from opentelemetry.exporter.otlp.proto.http._log_exporter import OTLPLogExporter
    from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

    return OTLPSpanExporter(), OTLPMetricExporter(), OTLPLogExporter()


def configure_telemetry() -> str:
    exporter = os.getenv("TELEMETRY_EXPORTER", "console")
    if exporter not in EXPORTERS:
        raise ValueError(f"TELEMETRY_EXPORTER must be one of {sorted(EXPORTERS)}, got {exporter!r}")
    logger.setLevel(logging.INFO)
    if exporter == "none":
        return exporter

    resource = build_resource()
    span_exporter, metric_exporter, log_exporter = build_exporters(exporter)
    interval_ms = int(os.getenv("OTEL_METRIC_EXPORT_INTERVAL", DEFAULT_METRIC_EXPORT_INTERVAL_MS))

    tracer_provider = TracerProvider(resource=resource)
    tracer_provider.add_span_processor(BatchSpanProcessor(span_exporter))
    trace.set_tracer_provider(tracer_provider)

    reader = PeriodicExportingMetricReader(metric_exporter, export_interval_millis=interval_ms)
    metrics.set_meter_provider(MeterProvider(resource=resource, metric_readers=[reader]))

    logger_provider = LoggerProvider(resource=resource)
    logger_provider.add_log_record_processor(BatchLogRecordProcessor(log_exporter))
    set_logger_provider(logger_provider)
    logger.addHandler(LoggingHandler(logger_provider=logger_provider))
    if exporter == "otlp":
        # Keep a human-readable copy in `docker compose logs app` as well.
        stream = logging.StreamHandler()
        stream.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
        logger.addHandler(stream)
    return exporter


def route_template(request: Request) -> str:
    route = request.scope.get("route")
    return getattr(route, "path", None) or UNMATCHED_ROUTE


def instrument_requests(app: FastAPI) -> None:
    """Record a server span, a request metric, and a log line for each request."""

    @app.middleware("http")
    async def record_request(request: Request, call_next):
        if request.url.path in UNTRACED_PATHS:
            return await call_next(request)

        started = time.perf_counter()
        parent = propagate.extract(request.headers)
        with tracer.start_as_current_span(request.method, context=parent, kind=SpanKind.SERVER) as span:
            status_code = 500
            error = None
            try:
                response = await call_next(request)
                status_code = response.status_code
                return response
            except Exception as exc:
                error = exc
                raise
            finally:
                route = route_template(request)
                attributes = {
                    "http.request.method": request.method,
                    "http.route": route,
                    "http.response.status_code": status_code,
                }
                span.update_name(f"{request.method} {route}")
                # The concrete path goes on spans and logs only; metrics keep the template.
                span.set_attributes({**attributes, "url.path": request.url.path})
                if status_code >= 500:
                    span.set_status(Status(StatusCode.ERROR))
                request_counter.add(1, attributes)
                request_duration.record(time.perf_counter() - started, attributes)
                log_extra = {
                    **attributes,
                    "url.path": request.url.path,
                    "duration_ms": round((time.perf_counter() - started) * 1000, 1),
                }
                if error is not None:
                    logger.error("request failed", exc_info=error, extra=log_extra)
                else:
                    level = logging.WARNING if status_code >= 500 else logging.INFO
                    logger.log(level, "request completed", extra=log_extra)
