import json

import pytest
from fastapi.testclient import TestClient

import evidence
import responder

TEST_ALERT = {
    "alerts": [
        {
            "status": "firing",
            "labels": {"alertname": "ResponderTest", "test": "true"},
            "annotations": {"summary": "Test notification; no incident to fix"},
        }
    ]
}
REAL_ALERT = {
    "status": "firing",
    "alerts": [
        {
            "status": "firing",
            "labels": {"alertname": "Order Tracker 5xx responses", "http_route": "/api/orders/{order_id}"},
            "annotations": {"summary": "Users get 5xx responses", "dashboard_url": "http://localhost:3000/d/x"},
            "fingerprint": "abc",
        }
    ],
}


@pytest.fixture
def handled(tmp_path, monkeypatch):
    monkeypatch.setattr(responder, "INCIDENTS_DIR", tmp_path)
    monkeypatch.setattr(responder, "dispatcher", responder.Dispatcher())
    monkeypatch.setattr(responder, "TOKEN", "")
    calls = []
    monkeypatch.setattr(responder, "handle_incident", calls.append)
    return calls


@pytest.fixture
def client():
    return TestClient(responder.app)


def test_test_alert_opens_incident_with_saved_payload(client, handled, tmp_path):
    response = client.post("/alerts", json=TEST_ALERT)
    assert response.status_code == 202
    result = response.json()["results"][0]
    assert result["status"] == "accepted"
    responder.dispatcher.executor.shutdown(wait=True)

    incident = handled[0]
    assert incident.alert.is_test
    assert incident.alert.endpoint is None
    saved = json.loads((tmp_path / result["incident_id"] / "alert.json").read_text())
    assert saved == TEST_ALERT


def test_repeated_alert_is_deduplicated(client, handled):
    first = client.post("/alerts", json=REAL_ALERT).json()["results"][0]
    second = client.post("/alerts", json=REAL_ALERT).json()["results"][0]
    assert first["status"] == "accepted"
    assert second["status"] == "duplicate"
    responder.dispatcher.executor.shutdown(wait=True)
    assert len(handled) == 1
    assert handled[0].alert.endpoint == "/api/orders/{order_id}"


def test_resolved_alert_does_not_start_agent(client, handled):
    payload = {"alerts": [{**REAL_ALERT["alerts"][0], "status": "resolved"}]}
    result = client.post("/alerts", json=payload).json()["results"][0]
    assert result == {"alert": "Order Tracker 5xx responses", "status": "ignored", "reason": "resolved"}
    assert handled == []


def test_malformed_payload_is_rejected(client, handled):
    assert client.post("/alerts", json={"alerts": "nope"}).status_code == 422
    assert client.post("/alerts", content=b"not json").status_code == 422


def test_token_is_required_when_configured(client, handled, monkeypatch):
    monkeypatch.setattr(responder, "TOKEN", "secret")
    assert client.post("/alerts", json=TEST_ALERT).status_code == 401
    headers = {"Authorization": "Bearer secret"}
    assert client.post("/alerts", json=TEST_ALERT, headers=headers).status_code == 202


def test_parse_answer_reads_trailer_even_with_markdown():
    text = """Investigated.

**INCIDENT:** 20260927T000000Z-x
ROOT CAUSE: day + 2 overflows the month
FIX: app/main.py uses timedelta
VERIFICATION: verify-recovery.sh -> RECOVERED
- ACTION: fixed.
RESULT: express lookups return 200 again"""
    answer = responder.parse_answer(text)
    assert answer["action"] == "fixed"
    assert answer["root_cause"] == "day + 2 overflows the month"
    assert answer["last_line"] == "RESULT: express lookups return 200 again"


def test_agent_env_drops_parent_session_variables(monkeypatch):
    monkeypatch.setenv("CLAUDECODE", "1")
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "parent")
    monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "keep-me")
    env = responder.agent_env()
    assert "CLAUDECODE" not in env
    assert "CLAUDE_CODE_SESSION_ID" not in env
    assert env["CLAUDE_CODE_OAUTH_TOKEN"] == "keep-me"


def test_agent_command_denies_by_default_and_never_allows_push():
    command = responder.agent_command()
    assert command[command.index("--permission-mode") + 1] == "dontAsk"
    assert "Bash(git push:*)" in command
    assert command[command.index("--tools") + 1] == "Read,Grep,Glob,Edit,Write,Bash"
    assert not any(tool.startswith("Bash(git push") for tool in responder.ALLOWED_TOOLS)


@pytest.mark.parametrize(
    "route, expected",
    [
        ("/api/orders/{order_id}", "/api/orders/{order_id}"),
        ('/api"} or {job=~".+', None),
        ("not-a-route", None),
        (None, None),
    ],
)
def test_alert_endpoint_is_validated_before_querying(route, expected):
    assert evidence.safe_route(route) == expected


@pytest.mark.parametrize(
    "path, expected",
    [
        ("/api/orders/express-1002", "/api/orders/express-1002"),
        ("/api/../admin", None),
        ("http://evil.example/api/x", None),
        ("/api/orders/x?y=1", None),
    ],
)
def test_failing_paths_are_validated_before_verification(path, expected):
    assert evidence.safe_path(path) == expected


def run_incident_with_fake_agent(tmp_path, monkeypatch, diffs):
    """Run handle_incident with evidence and agent stubbed; `diffs` = git diff before, after."""
    monkeypatch.setattr(responder, "INCIDENTS_DIR", tmp_path)
    monkeypatch.setattr(responder, "collect_evidence", lambda endpoint, repo: evidence.Evidence(endpoint=endpoint))
    outputs = iter(diffs)
    monkeypatch.setattr(responder, "working_tree_changes", lambda: next(outputs))
    monkeypatch.setattr(
        responder,
        "run_agent",
        lambda incident, prompt: {"exit_code": 0, "answer": responder.parse_answer("ACTION: none")},
    )
    incident = responder.Incident(responder.parse_alerts(TEST_ALERT)[0], TEST_ALERT)
    responder.handle_incident(incident)
    return incident


def test_fix_diff_excludes_changes_made_before_the_agent(tmp_path, monkeypatch):
    incident = run_incident_with_fake_agent(tmp_path, monkeypatch, ["human edit", "human edit"])
    assert (incident.dir / "baseline.diff").read_text() == "human edit"
    assert not (incident.dir / "fix.diff").exists()
    assert incident.record["status"] == "closed"


def test_fix_diff_is_saved_when_the_agent_changes_code(tmp_path, monkeypatch):
    incident = run_incident_with_fake_agent(tmp_path, monkeypatch, ["", "agent fix"])
    assert (incident.dir / "fix.diff").read_text() == "agent fix"
    assert not (incident.dir / "baseline.diff").exists()
