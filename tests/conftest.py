import os

# Tests install in-memory OpenTelemetry providers instead of exporting anywhere.
os.environ.setdefault("TELEMETRY_EXPORTER", "none")
