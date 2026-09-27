# Evidence

- Endpoint: `not given in alert`
- Window: last 15 minutes
- Deployed version(s): dev
- Failing paths: none found

## Requests by route and status (Prometheus)

- `/` status 200: 0.0 (version dev)
- `/api/orders` status 200: 0.0 (version dev)

## Warning and error logs (Loki)

- no warning or error logs

## Error traces (Tempo)

- no error traces

## Recent commits

- 43e115a 2026-09-27T07:02:32+05:00 feat(alerting): add Grafana alert for 5xx responses per endpoint
- a060a4b 2026-09-27T06:53:57+05:00 feat(observability): add Collector, Prometheus, Loki, Tempo, and Grafana
- ff1a0c1 2026-09-27T06:48:22+05:00 feat(telemetry): add OpenTelemetry metrics, traces, and logs for order lookups
- 72de447 2026-09-25T18:46:35+02:00 Simplify local Compose startup
- 9f61e92 2026-09-25T11:17:44+02:00 Add order tracker starter
