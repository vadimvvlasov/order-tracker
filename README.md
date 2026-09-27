# Order Tracker

A small order tracking app for the AI Dev Tools Zoomcamp observability homework. It includes a web page, API, tests, and a Docker Compose setup. You add telemetry, alerts, and an incident responder in Homework 4.

The main user flow is creating an order and checking its status. Three sample orders are created on first startup.

## Run it

You need Docker with Compose. To run the tests, you also need Python 3.11+ and `uv`.

```bash
docker compose up --build -d --wait
```

Open <http://127.0.0.1:8000>. The API is at `/api/orders`, and the health check is at `/healthz`. Data is stored in a Docker volume and survives container recreation.

If port 8000 is occupied, set `ORDER_TRACKER_PORT`, for example:

```bash
ORDER_TRACKER_PORT=18080 docker compose up --build -d --wait
```

Run tests with `uv run --frozen pytest -q`. Stop the app with `docker compose down`. Add `-v` only if you also want to delete the order data.

## API

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/` | Web page |
| GET | `/healthz` | Database health check |
| GET | `/api/orders` | List orders |
| POST | `/api/orders` | Create an order |
| GET | `/api/orders/{id}` | Check an order |
| PATCH | `/api/orders/{id}` | Change an order status |

The app uses SQLite to keep setup small. Run one app container at a time. The course exercise is about detecting and handling an incident, not scaling the database.

## Observability and incident response (Homework 4)

What was added on top of the starter, and where to look:

| Piece | Files | Why it matters |
| --- | --- | --- |
| OpenTelemetry for requests and order lookups | `app/telemetry.py`, `tests/test_telemetry.py` | Request counter and latency histogram by `http.route` (template, not raw path) and status code; server span plus `order.lookup` span; logs share the trace id. No customer data in attributes. |
| Telemetry pipeline | `observability/compose.yaml`, `collector.yaml`, `prometheus.yaml`, `loki.yaml`, `tempo.yaml` | App → OTel Collector → Prometheus (metrics), Loki (logs), Tempo (traces). Included from the root `compose.yaml`, so one `docker compose up` starts everything. All ports bind 127.0.0.1. |
| Grafana | `observability/grafana-*.yaml`, `observability/dashboard.json` | Provisioned datasources with log → trace and span → logs links; dashboard for request counts, 5xx, latency, logs, traces. |
| Alert on user impact | `observability/alerts.yaml` | 5xx per route over 5 minutes, endpoint/window/dashboard link in annotations, no data = Normal, webhook to the responder. |
| Incident responder | `incident-response/responder.py`, `evidence.py`, `responder-task.md`, `runbooks/` | `POST /alerts` on port 8001 opens an incident, collects read-only evidence, and runs Claude Code headless with a tool allowlist. The responder, not the agent, verifies recovery. |
| Incident evidence | `incident-response/incidents/` | Test notifications from Question 5 and the real `express-1002` incident from Question 6. |

Run it:

```bash
docker compose up --build -d --wait                       # app :8000, Grafana :3000
uv run --frozen python incident-response/responder.py     # responder :8001 (127.0.0.1 and docker0)
curl -i http://localhost:8000/api/orders/express-1002      # before the fix: 500 → alert → responder
```

Grafana: <http://localhost:3000/d/order-tracker/order-tracker> (anonymous admin, local only).

### Responder guardrails

- Evidence first: fixed, time-boxed, read-only queries to Prometheus, Loki, Tempo, and `git log`. The alert payload is validated before any of it goes into a query.
- Agent session: `--tools Read,Grep,Glob,Edit,Write,Bash`, `--permission-mode dontAsk`, and an allowlist. It may edit `app/` and `tests/`, run `pytest`, `runbooks/redeploy.sh`, and `runbooks/verify-recovery.sh`. It may not commit, push, or use the web. No user hooks, plugins, or MCP servers (`--setting-sources project --strict-mcp-config`).
- The alert text is marked as data, not instructions. Test alerts (`test=true`) get no action.
- Repeated notifications for the same alert and route start one agent run, not many (15 minute cooldown).
- After the agent says `ACTION: fixed`, the responder runs `verify-recovery.sh` on the failing paths itself. Only a passing check marks the incident `recovered`; the diff waits for a human to commit.
- Listens on 127.0.0.1 and the docker0 address Grafana uses, never 0.0.0.0. Optional `RESPONDER_TOKEN` enables a bearer token check.

### The incident

[`incidents/20260927T025225Z-order-tracker-5xx-responses`](incident-response/incidents/20260927T025225Z-order-tracker-5xx-responses/report.md): `GET /api/orders/express-1002` returned 500 with `ValueError: day is out of range for month`. The express delivery estimate used `placed_at.replace(day=placed_at.day + 2)`, and the seeded order is placed on the last day of the previous month. The agent changed it to `placed_at + timedelta(days=2)` and added two regression tests, then redeployed. The responder's own check returned 200 three times out of three. Took 10 turns and 42 s.
