#!/usr/bin/env bash
# Rebuild and restart only the app container from the current working tree.
# The telemetry stack keeps running, so recovery shows up on the same dashboard.
set -euo pipefail

cd "$(dirname "$0")/../.."
docker compose up --build -d --wait --no-deps app
docker compose ps app
