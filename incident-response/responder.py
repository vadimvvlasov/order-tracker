"""Incident responder: Grafana alert webhook -> evidence -> headless coding agent.

POST /alerts accepts a Grafana (Alertmanager-style) webhook. For each new firing
alert it opens incidents/<id>/, saves the alert and a read-only evidence packet,
and starts Claude Code in headless mode with a fixed tool allowlist. When the
agent is done, the responder re-checks the failing paths itself: the model's
"fixed" is a claim, the verification script decides.

Run on the host (it needs the repo, Docker, and the agent CLI):

    uv run --frozen python incident-response/responder.py
"""

import json
import logging
import os
import re
import socket
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import uvicorn
from fastapi import FastAPI, HTTPException, Request

from evidence import collect_evidence, render_markdown

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent
INCIDENTS_DIR = Path(os.getenv("RESPONDER_INCIDENTS_DIR", HERE / "incidents"))
TASK_TEMPLATE = HERE / "responder-task.md"
VERIFY_SCRIPT = HERE / "runbooks" / "verify-recovery.sh"

PORT = int(os.getenv("RESPONDER_PORT", "8001"))
# Loopback for local curl, docker0 for Grafana via host.docker.internal. Never 0.0.0.0:
# this service starts an agent that can edit code, so it must not be reachable from the LAN.
HOSTS = [h.strip() for h in os.getenv("RESPONDER_HOSTS", "127.0.0.1,172.17.0.1").split(",") if h.strip()]
TOKEN = os.getenv("RESPONDER_TOKEN", "")
AGENT_BIN = os.getenv("RESPONDER_AGENT_BIN", "claude")
AGENT_MODEL = os.getenv("RESPONDER_MODEL", "")
AGENT_TIMEOUT_SECONDS = int(os.getenv("RESPONDER_AGENT_TIMEOUT", "1200"))
AGENT_MAX_BUDGET_USD = os.getenv("RESPONDER_MAX_BUDGET_USD", "3")
COOLDOWN_SECONDS = int(os.getenv("RESPONDER_COOLDOWN", "900"))
MAX_PAYLOAD_BYTES = 256 * 1024
MAX_ANNOTATION_CHARS = 2000

# Autonomy policy. The agent runs with --permission-mode dontAsk, so anything not
# listed here is denied without a prompt. It can read the repo, edit app/ and tests/,
# run tests, redeploy the app container, and probe the app. It cannot commit, push,
# browse the web, or touch the telemetry, alert, or responder configuration.
ALLOWED_TOOLS = [
    "Read",
    "Grep",
    "Glob",
    "Edit(./app/**)",
    "Edit(./tests/**)",
    "Bash(uv run --frozen pytest:*)",
    "Bash(incident-response/runbooks/redeploy.sh)",
    "Bash(incident-response/runbooks/verify-recovery.sh:*)",
    "Bash(git status:*)",
    "Bash(git diff:*)",
    "Bash(git log:*)",
]
# The only built-in tools the agent session has at all (no subagents, schedulers, web).
AVAILABLE_TOOLS = "Read,Grep,Glob,Edit,Write,Bash"
DISALLOWED_TOOLS = [
    "WebFetch",
    "WebSearch",
    "Bash(git commit:*)",
    "Bash(git push:*)",
    "Bash(git reset:*)",
    "Bash(git checkout:*)",
]
# Variables that make a child `claude` think it runs inside this session.
INHERITED_SESSION_VARS = re.compile(r"^CLAUDE(CODE$|_CODE_|_PID$|_EFFORT$)")
KEPT_AGENT_VARS = {"CLAUDE_CODE_OAUTH_TOKEN", "CLAUDE_CODE_USE_BEDROCK", "CLAUDE_CODE_USE_VERTEX"}
ANSWER_FIELDS = ("INCIDENT", "ROOT CAUSE", "FIX", "VERIFICATION", "ACTION", "RESULT")

log = logging.getLogger("incident_responder")


@dataclass
class Alert:
    name: str
    status: str
    labels: dict
    annotations: dict
    endpoint: str | None
    fingerprint: str | None
    starts_at: str | None
    generator_url: str | None
    dashboard_url: str | None

    @property
    def is_test(self) -> bool:
        return str(self.labels.get("test", "")).lower() == "true"

    @property
    def dedup_key(self) -> str:
        return f"{self.name}|{self.endpoint or '-'}"

    def to_dict(self) -> dict:
        return {**self.__dict__, "is_test": self.is_test}


def parse_alerts(payload: dict) -> list[Alert]:
    if not isinstance(payload, dict) or not isinstance(payload.get("alerts"), list):
        raise ValueError("payload must be a JSON object with an 'alerts' list")
    alerts = []
    for raw in payload["alerts"]:
        if not isinstance(raw, dict):
            raise ValueError("each alert must be a JSON object")
        labels = {str(k): str(v) for k, v in (raw.get("labels") or {}).items()}
        annotations = {
            str(k): str(v)[:MAX_ANNOTATION_CHARS] for k, v in (raw.get("annotations") or {}).items()
        }
        alerts.append(
            Alert(
                name=labels.get("alertname", "unnamed-alert"),
                status=str(raw.get("status", payload.get("status", "firing"))),
                labels=labels,
                annotations=annotations,
                endpoint=labels.get("http_route") or annotations.get("endpoint"),
                fingerprint=raw.get("fingerprint"),
                starts_at=raw.get("startsAt"),
                generator_url=raw.get("generatorURL"),
                dashboard_url=raw.get("dashboardURL") or annotations.get("dashboard_url"),
            )
        )
    return alerts


def slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:48] or "alert"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def parse_answer(text: str) -> dict:
    answer = {}
    for line in text.splitlines():
        clean = line.replace("**", "").replace("`", "").strip().lstrip("-*> ").strip()
        for field_name in ANSWER_FIELDS:
            prefix = f"{field_name}:"
            if clean.upper().startswith(prefix):
                answer[field_name.lower().replace(" ", "_")] = clean[len(prefix):].strip()
    action_words = answer.get("action", "").lower().split()
    answer["action"] = action_words[0].strip(".,") if action_words else "unknown"
    lines = [line for line in text.strip().splitlines() if line.strip()]
    answer["last_line"] = lines[-1].strip() if lines else ""
    return answer


def agent_env() -> dict:
    return {
        key: value
        for key, value in os.environ.items()
        if key in KEPT_AGENT_VARS or not INHERITED_SESSION_VARS.match(key)
    }


def agent_command() -> list[str]:
    command = [
        AGENT_BIN,
        "-p",
        "--output-format", "stream-json",
        "--verbose",
        "--permission-mode", "dontAsk",
        # Project settings only: no user hooks, plugins, or MCP servers in the responder.
        "--setting-sources", "project",
        "--strict-mcp-config",
        "--max-budget-usd", AGENT_MAX_BUDGET_USD,
        "--tools", AVAILABLE_TOOLS,
        "--allowedTools", *ALLOWED_TOOLS,
        "--disallowedTools", *DISALLOWED_TOOLS,
    ]
    if AGENT_MODEL:
        command += ["--model", AGENT_MODEL]
    return command


def build_prompt(incident_id: str, alert: Alert, evidence_md: str) -> str:
    return (
        TASK_TEMPLATE.read_text()
        .replace("{{INCIDENT_ID}}", incident_id)
        .replace("{{ALERT_JSON}}", json.dumps(alert.to_dict(), indent=2))
        .replace("{{EVIDENCE}}", evidence_md)
    )


class Incident:
    def __init__(self, alert: Alert, payload: dict):
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        self.id = f"{stamp}-{slugify(alert.name)}"
        self.dir = INCIDENTS_DIR / self.id
        self.dir.mkdir(parents=True, exist_ok=False)
        self.alert = alert
        self.record = {
            "id": self.id,
            "status": "received",
            "created_at": utc_now(),
            "alert": alert.to_dict(),
            "timeline": [],
        }
        self.write_json("alert.json", payload)
        self.transition("received", f"{alert.status} alert {alert.name} for {alert.endpoint or 'no endpoint'}")

    def write_json(self, name: str, data) -> None:
        (self.dir / name).write_text(json.dumps(data, indent=2, default=str) + "\n")

    def transition(self, status: str, note: str) -> None:
        self.record["status"] = status
        self.record["timeline"].append({"at": utc_now(), "status": status, "note": note})
        self.write_json("incident.json", self.record)
        log.info("incident %s: %s (%s)", self.id, status, note)


def run_agent(incident: Incident, prompt: str) -> dict:
    (incident.dir / "prompt.md").write_text(prompt)
    command = agent_command()
    started = time.monotonic()
    result_event, init_event = {}, {}
    with (incident.dir / "transcript.jsonl").open("w") as transcript:
        process = subprocess.Popen(
            command,
            cwd=REPO_ROOT,
            env=agent_env(),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        timer = threading.Timer(AGENT_TIMEOUT_SECONDS, process.kill)
        timer.start()
        try:
            process.stdin.write(prompt)
            process.stdin.close()
            for line in process.stdout:
                transcript.write(line)
                transcript.flush()
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if event.get("type") == "system" and event.get("subtype") == "init":
                    init_event = event
                elif event.get("type") == "result":
                    result_event = event
            exit_code = process.wait()
        finally:
            timer.cancel()
    answer_text = result_event.get("result") or ""
    (incident.dir / "response.md").write_text(answer_text + "\n")
    return {
        "command": command,
        "exit_code": exit_code,
        "timed_out": time.monotonic() - started >= AGENT_TIMEOUT_SECONDS,
        "duration_s": round(time.monotonic() - started, 1),
        "model": init_event.get("model"),
        "permission_mode": init_event.get("permissionMode"),
        "tools": init_event.get("tools"),
        "num_turns": result_event.get("num_turns"),
        "cost_usd": result_event.get("total_cost_usd"),
        "is_error": result_event.get("is_error"),
        "permission_denials": result_event.get("permission_denials", []),
        "answer": parse_answer(answer_text),
    }


def verify_recovery(paths: list[str]) -> dict:
    result = subprocess.run(
        [str(VERIFY_SCRIPT), *paths], cwd=REPO_ROOT, capture_output=True, text=True, timeout=60
    )
    return {"paths": paths, "exit_code": result.returncode, "output": result.stdout + result.stderr}


def git_output(*args: str) -> str:
    result = subprocess.run(["git", *args], cwd=REPO_ROOT, capture_output=True, text=True, timeout=30)
    return result.stdout


def working_tree_changes() -> str:
    """Uncommitted changes under app/ and tests/, including new files."""
    diff = git_output("diff", "--", "app", "tests")
    untracked = git_output("ls-files", "--others", "--exclude-standard", "--", "app", "tests")
    return diff + (f"\n# untracked files:\n{untracked}" if untracked else "")


def write_report(incident: Incident) -> None:
    record = incident.record
    alert, agent = record["alert"], record.get("agent", {})
    answer = agent.get("answer", {})
    verification = record.get("verification")
    lines = [
        f"# Incident {record['id']}",
        "",
        f"- Status: **{record['status']}**",
        f"- Alert: {alert['name']} ({alert['status']}), endpoint `{alert['endpoint']}`",
        f"- Summary: {alert['annotations'].get('summary', '')}",
        f"- Dashboard: {alert['dashboard_url'] or 'n/a'}",
        f"- Deployed version(s): {', '.join(record.get('deployed_versions', [])) or 'unknown'}",
        f"- Agent: `{AGENT_BIN}` model `{agent.get('model')}`, {agent.get('num_turns')} turns, "
        f"{agent.get('duration_s')} s, exit {agent.get('exit_code')}",
        f"- Permission denials: {len(agent.get('permission_denials', []))}",
        f"- Agent action: **{answer.get('action', 'n/a')}**",
        f"- Root cause (agent): {answer.get('root_cause', 'n/a')}",
        f"- Fix (agent): {answer.get('fix', 'n/a')}",
        f"- Verification (responder): "
        + (
            f"`verify-recovery.sh {' '.join(verification['paths'])}` exit {verification['exit_code']}"
            if verification
            else "not run"
        ),
        "",
        "## Files",
        "",
        "- `alert.json` raw webhook, `evidence.md` / `evidence.json` what the agent saw",
        "- `prompt.md` exact task, `transcript.jsonl` full agent session, `response.md` final answer",
        "- `fix.diff` agent's change left for human review (only if it changed app/ or tests/)",
        "- `baseline.diff` changes that were already uncommitted before the agent ran, if any",
        "- `incident.json` timeline",
        "",
        "## Timeline",
        "",
    ]
    lines += [f"- {step['at']} {step['status']}: {step['note']}" for step in record["timeline"]]
    (incident.dir / "report.md").write_text("\n".join(lines) + "\n")


def handle_incident(incident: Incident) -> None:
    try:
        evidence = collect_evidence(incident.alert.endpoint, REPO_ROOT)
        incident.write_json("evidence.json", evidence.to_dict())
        evidence_md = render_markdown(evidence)
        (incident.dir / "evidence.md").write_text(evidence_md)
        incident.record["deployed_versions"] = evidence.deployed_versions
        incident.transition(
            "evidence_collected",
            f"{len(evidence.error_logs)} error logs, {len(evidence.error_traces)} error traces, "
            f"failing paths {evidence.failing_paths or 'none'}",
        )

        baseline = working_tree_changes()
        if baseline:
            (incident.dir / "baseline.diff").write_text(baseline)
        incident.transition("agent_running", f"{AGENT_BIN} headless, allowlist of {len(ALLOWED_TOOLS)} tools")
        agent = run_agent(incident, build_prompt(incident.id, incident.alert, evidence_md))
        incident.record["agent"] = agent
        action = agent["answer"]["action"]
        incident.transition("agent_done", f"action={action} exit={agent['exit_code']}")

        changes = working_tree_changes()
        if changes != baseline:
            (incident.dir / "fix.diff").write_text(changes)

        if action == "fixed" and evidence.failing_paths:
            verification = verify_recovery(evidence.failing_paths)
            incident.record["verification"] = verification
            if verification["exit_code"] == 0:
                incident.transition("recovered", "failing paths no longer return 5xx; fix awaits human review")
            else:
                incident.transition("escalated", "agent reported a fix but verification failed")
        elif action == "none":
            incident.transition("closed", "agent found nothing to fix")
        else:
            incident.transition("escalated", f"agent action '{action}' needs a human")
    except Exception as exc:
        log.exception("incident %s failed", incident.id)
        incident.transition("escalated", f"responder error: {type(exc).__name__}: {exc}")
    finally:
        write_report(incident)


class Dispatcher:
    """Serializes agent runs and drops repeats of an alert that is already handled."""

    def __init__(self):
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="responder")
        self.lock = threading.Lock()
        self.last_seen: dict[str, float] = {}

    def submit(self, alert: Alert, payload: dict) -> dict:
        now = time.monotonic()
        with self.lock:
            seen = self.last_seen.get(alert.dedup_key)
            if seen is not None and now - seen < COOLDOWN_SECONDS:
                return {"alert": alert.name, "status": "duplicate", "endpoint": alert.endpoint}
            self.last_seen[alert.dedup_key] = now
        incident = Incident(alert, payload)
        self.executor.submit(handle_incident, incident)
        return {"alert": alert.name, "status": "accepted", "incident_id": incident.id}


app = FastAPI(title="Order Tracker incident responder")
dispatcher = Dispatcher()


@app.get("/healthz")
def health():
    return {"status": "ok"}


@app.post("/alerts", status_code=202)
async def receive_alerts(request: Request):
    if TOKEN and request.headers.get("authorization") != f"Bearer {TOKEN}":
        raise HTTPException(401, "missing or wrong bearer token")
    body = await request.body()
    if len(body) > MAX_PAYLOAD_BYTES:
        raise HTTPException(413, "alert payload too large")
    try:
        payload = json.loads(body)
        alerts = parse_alerts(payload)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    results = []
    for alert in alerts:
        if alert.status != "firing":
            results.append({"alert": alert.name, "status": "ignored", "reason": alert.status})
            continue
        results.append(dispatcher.submit(alert, payload))
    return {"results": results}


@app.get("/incidents")
def list_incidents():
    records = []
    for path in sorted(INCIDENTS_DIR.glob("*/incident.json"), reverse=True):
        record = json.loads(path.read_text())
        records.append({"id": record["id"], "status": record["status"], "alert": record["alert"]["name"]})
    return records


@app.get("/incidents/{incident_id}")
def get_incident(incident_id: str):
    path = INCIDENTS_DIR / incident_id / "incident.json"
    if not re.fullmatch(r"[A-Za-z0-9-]+", incident_id) or not path.exists():
        raise HTTPException(404, "incident not found")
    return json.loads(path.read_text())


def bind_socket(host: str, port: int) -> socket.socket:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind((host, port))
    return sock


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    INCIDENTS_DIR.mkdir(parents=True, exist_ok=True)
    sockets = [bind_socket(host, PORT) for host in HOSTS]
    log.info("listening on %s, port %d", ", ".join(HOSTS), PORT)
    uvicorn.Server(uvicorn.Config(app, log_level="info")).run(sockets=sockets)


if __name__ == "__main__":
    main()
