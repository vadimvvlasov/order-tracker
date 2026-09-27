"""Collect a bounded, read-only evidence packet for one alert.

Every query is fixed here (an allowlist), time-boxed, and size-limited. Values
taken from the alert payload are validated before they reach a query, because
the payload comes from outside this process.
"""

import json
import re
import subprocess
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

PROMETHEUS_URL = "http://127.0.0.1:9090"
LOKI_URL = "http://127.0.0.1:3100"
TEMPO_URL = "http://127.0.0.1:3200"
SERVICE_NAME = "order-tracker"
WINDOW_SECONDS = 15 * 60
QUERY_TIMEOUT_SECONDS = 5
MAX_LOG_LINES = 20
MAX_TRACES = 5
MAX_STACKTRACE_CHARS = 4000
SAFE_ROUTE = re.compile(r"^/[A-Za-z0-9_{}./-]{0,120}$")
SAFE_PATH = re.compile(r"^/api/[A-Za-z0-9_./-]{1,120}$")


@dataclass
class Evidence:
    endpoint: str | None
    window_seconds: int = WINDOW_SECONDS
    request_counts: list = field(default_factory=list)
    deployed_versions: list = field(default_factory=list)
    error_logs: list = field(default_factory=list)
    error_traces: list = field(default_factory=list)
    failing_paths: list = field(default_factory=list)
    recent_commits: list = field(default_factory=list)
    errors: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return dict(self.__dict__)


def safe_route(value: str | None) -> str | None:
    if value and SAFE_ROUTE.match(value) and '"' not in value:
        return value
    return None


def safe_path(value: str | None) -> str | None:
    if value and SAFE_PATH.match(value) and ".." not in value:
        return value
    return None


def http_get_json(base_url: str, path: str, params: dict) -> dict:
    url = f"{base_url}{path}?{urllib.parse.urlencode(params)}"
    with urllib.request.urlopen(url, timeout=QUERY_TIMEOUT_SECONDS) as response:
        return json.loads(response.read())


def query_request_counts(endpoint: str | None) -> list:
    route_filter = f', http_route="{endpoint}"' if endpoint else ""
    query = (
        "sum by (http_route, http_response_status_code, service_version) "
        f'(increase(order_tracker_http_requests_total{{service_name="{SERVICE_NAME}"{route_filter}}}'
        f"[{WINDOW_SECONDS}s]))"
    )
    data = http_get_json(PROMETHEUS_URL, "/api/v1/query", {"query": query})
    return [
        {**row["metric"], "requests": round(float(row["value"][1]), 1)}
        for row in data["data"]["result"]
    ]


def query_error_logs(endpoint: str | None) -> list:
    route_filter = f' | http_route="{endpoint}"' if endpoint else ""
    query = f'{{service_name="{SERVICE_NAME}"}} | severity_text=~"ERROR|WARN"{route_filter}'
    now_ns = time.time_ns()
    data = http_get_json(
        LOKI_URL,
        "/loki/api/v1/query_range",
        {
            "query": query,
            "start": now_ns - WINDOW_SECONDS * 1_000_000_000,
            "end": now_ns,
            "limit": MAX_LOG_LINES,
            "direction": "backward",
        },
    )
    logs = []
    for stream in data["data"]["result"]:
        labels = stream["stream"]
        for value in stream["values"]:
            logs.append(
                {
                    "time_ns": value[0],
                    "message": value[1],
                    "severity": labels.get("severity_text"),
                    "http_route": labels.get("http_route"),
                    "url_path": labels.get("url_path"),
                    "status_code": labels.get("http_response_status_code"),
                    "service_version": labels.get("service_version"),
                    "trace_id": labels.get("trace_id"),
                    "exception_type": labels.get("exception_type"),
                    "exception_message": labels.get("exception_message"),
                    "exception_stacktrace": (labels.get("exception_stacktrace") or "")[
                        :MAX_STACKTRACE_CHARS
                    ],
                }
            )
    logs.sort(key=lambda log: log["time_ns"], reverse=True)
    return logs[:MAX_LOG_LINES]


def span_attributes(span: dict) -> dict:
    attributes = {}
    for attribute in span.get("attributes", []):
        value = attribute.get("value", {})
        attributes[attribute["key"]] = next(iter(value.values()), None) if value else None
    return attributes


def summarize_trace(trace: dict) -> list:
    resource_spans = trace.get("batches") or trace.get("resourceSpans") or []
    spans = []
    for resource in resource_spans:
        for scope in resource.get("scopeSpans", resource.get("instrumentationLibrarySpans", [])):
            for span in scope.get("spans", []):
                spans.append(
                    {
                        "name": span.get("name"),
                        "status": span.get("status", {}),
                        "attributes": span_attributes(span),
                        "events": [
                            {"name": event.get("name"), "attributes": span_attributes(event)}
                            for event in span.get("events", [])
                        ],
                    }
                )
    return spans


def query_error_traces(endpoint: str | None) -> list:
    route_filter = f' && span.http.route="{endpoint}"' if endpoint else ""
    query = f'{{resource.service.name="{SERVICE_NAME}" && status=error{route_filter}}}'
    now = int(time.time())
    data = http_get_json(
        TEMPO_URL,
        "/api/search",
        {"q": query, "start": now - WINDOW_SECONDS, "end": now, "limit": MAX_TRACES},
    )
    traces = []
    for found in data.get("traces", [])[:MAX_TRACES]:
        trace_id = found["traceID"]
        detail = http_get_json(TEMPO_URL, f"/api/traces/{trace_id}", {})
        traces.append(
            {
                "trace_id": trace_id,
                "root": found.get("rootTraceName"),
                "duration_ms": found.get("durationMs"),
                "spans": summarize_trace(detail.get("trace", detail)),
            }
        )
    return traces


def query_recent_commits(repo: Path) -> list:
    result = subprocess.run(
        ["git", "log", "--format=%h %cI %s", "-5"],
        cwd=repo,
        capture_output=True,
        text=True,
        timeout=QUERY_TIMEOUT_SECONDS,
        check=True,
    )
    return result.stdout.splitlines()


def collect_failing_paths(evidence: Evidence) -> list:
    paths = [log["url_path"] for log in evidence.error_logs if (log.get("status_code") or "").startswith("5")]
    for trace in evidence.error_traces:
        for span in trace["spans"]:
            paths.append(span["attributes"].get("url.path"))
    return sorted({path for path in map(safe_path, paths) if path})


def collect_evidence(endpoint: str | None, repo: Path) -> Evidence:
    evidence = Evidence(endpoint=safe_route(endpoint))
    steps = {
        "request_counts": lambda: query_request_counts(evidence.endpoint),
        "error_logs": lambda: query_error_logs(evidence.endpoint),
        "error_traces": lambda: query_error_traces(evidence.endpoint),
        "recent_commits": lambda: query_recent_commits(repo),
    }
    for name, step in steps.items():
        try:
            setattr(evidence, name, step())
        except Exception as exc:  # recorded, not raised: partial evidence beats none
            evidence.errors[name] = f"{type(exc).__name__}: {exc}"
    evidence.deployed_versions = sorted(
        {row.get("service_version") for row in evidence.request_counts if row.get("service_version")}
    )
    evidence.failing_paths = collect_failing_paths(evidence)
    return evidence


def render_markdown(evidence: Evidence) -> str:
    lines = [
        "# Evidence",
        "",
        f"- Endpoint: `{evidence.endpoint or 'not given in alert'}`",
        f"- Window: last {evidence.window_seconds // 60} minutes",
        f"- Deployed version(s): {', '.join(evidence.deployed_versions) or 'unknown'}",
        f"- Failing paths: {', '.join(f'`{p}`' for p in evidence.failing_paths) or 'none found'}",
        "",
        "## Requests by route and status (Prometheus)",
        "",
    ]
    for row in evidence.request_counts:
        lines.append(
            f"- `{row.get('http_route')}` status {row.get('http_response_status_code')}: "
            f"{row['requests']} (version {row.get('service_version')})"
        )
    if not evidence.request_counts:
        lines.append("- no requests recorded")
    lines += ["", "## Warning and error logs (Loki)", ""]
    for log in evidence.error_logs[:5]:
        lines.append(
            f"- {log['severity']} {log['message']} path={log['url_path']} status={log['status_code']} "
            f"trace_id={log['trace_id']} exception={log['exception_type']}: {log['exception_message']}"
        )
        if log["exception_stacktrace"]:
            lines += ["", "```text", log["exception_stacktrace"].rstrip(), "```", ""]
    if not evidence.error_logs:
        lines.append("- no warning or error logs")
    lines += ["", "## Error traces (Tempo)", ""]
    for trace in evidence.error_traces:
        lines.append(f"- trace `{trace['trace_id']}` {trace['root']} ({trace['duration_ms']} ms)")
        for span in trace["spans"]:
            status = span["status"].get("code") or span["status"].get("message") or ""
            lines.append(f"  - span `{span['name']}` {status} {json.dumps(span['attributes'])}")
            for event in span["events"]:
                lines.append(
                    f"    - event {event['name']}: {event['attributes'].get('exception.type')}: "
                    f"{event['attributes'].get('exception.message')}"
                )
    if not evidence.error_traces:
        lines.append("- no error traces")
    lines += ["", "## Recent commits", ""]
    lines += [f"- {commit}" for commit in evidence.recent_commits] or ["- unavailable"]
    if evidence.errors:
        lines += ["", "## Collection errors", ""]
        lines += [f"- {name}: {error}" for name, error in evidence.errors.items()]
    return "\n".join(lines) + "\n"
