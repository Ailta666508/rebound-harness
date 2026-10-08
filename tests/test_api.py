"""Exercise the inspector against real journals and the separate demo provider."""

import json
import sqlite3

import pytest
from fastapi.testclient import TestClient

from rebound.api import create_app


@pytest.fixture
def client(tmp_path):
    with TestClient(create_app(tmp_path), base_url="http://127.0.0.1") as value:
        yield value


def test_demo_survives_app_restart_and_resumes_without_duplicate_effects(tmp_path):
    with TestClient(create_app(tmp_path), base_url="http://127.0.0.1") as client:
        response = client.post("/api/demo", json={"scenario": "lost_ack", "steps": 4})
        assert response.status_code == 201
        run = response.json()
        assert run["status"] == "completed"
        assert run["metrics"]["duplicate_effects"] == 0
        assert run["metrics"]["effects"] == 4
        assert any(event["kind"] == "recovery.decision" for event in run["events"])
    with TestClient(create_app(tmp_path), base_url="http://127.0.0.1") as restarted:
        persisted = restarted.get(f"/api/runs/{run['id']}").json()
        assert persisted["events"] == run["events"]
        response = restarted.post(f"/api/runs/{run['id']}/resume", json={})
        assert response.status_code == 200
        assert response.json()["metrics"]["effects"] == 4
        assert restarted.get("/api/runs").json()[0]["id"] == run["id"]


def test_operator_confirmation_requires_explicit_verified_result(tmp_path):
    with TestClient(create_app(tmp_path), base_url="http://127.0.0.1") as client:
        run = client.post("/api/demo", json={"scenario": "unavailable", "steps": 3}).json()
        assert run["status"] == "needs_review"
        operation = next(op for op in run["operations"] if op["status"] == "unknown")
        url = f"/api/runs/{run['id']}/operations/{operation['id']}/resolve"
        assert client.post(url, json={"result": {}, "note": ""}).status_code == 422
        # Test operator independently consults provider state; the recovery policy
        # cannot access this oracle, just as in the benchmark protocol.
        with sqlite3.connect(tmp_path / "demo-provider.sqlite") as db:
            result = json.loads(
                db.execute(
                    "SELECT result FROM effects WHERE operation_id=?", (operation["id"],)
                ).fetchone()[0]
            )
        response = client.post(
            url,
            json={"result": result, "note": "Operator checked the independent provider ledger."},
        )
        assert response.status_code == 200
        assert response.json()["status"] == "completed"
        assert response.json()["metrics"]["duplicate_effects"] == 0
        assert any(event["kind"] == "recovery.manual" for event in response.json()["events"])
        assert (
            client.post(
                url, json={"result": result, "note": "Second confirmation is invalid."}
            ).status_code
            == 409
        )


def test_sse_cursor_emits_only_new_committed_events(client):
    run = client.post("/api/demo", json={"scenario": "clean", "steps": 2}).json()
    cursor = run["events"][1]["seq"]
    response = client.get(f"/api/runs/{run['id']}/events", headers={"Last-Event-ID": str(cursor)})
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    ids = [
        int(line.removeprefix("id: "))
        for line in response.text.splitlines()
        if line.startswith("id: ")
    ]
    assert ids == [event["seq"] for event in run["events"] if event["seq"] > cursor]
    assert (
        client.get(f"/api/runs/{run['id']}/events", headers={"Last-Event-ID": "bad"}).status_code
        == 400
    )


def test_unknown_api_route_is_not_swallowed_by_static_frontend(client):
    assert client.get("/api/does-not-exist").status_code == 404
    assert client.get("/api/runs/missing").status_code == 404
    assert client.post("/api/runs/missing/resume", json={}).status_code == 404


@pytest.mark.parametrize(
    "body", [{"scenario": "invalid"}, {"policy": "invalid"}, {"steps": 0}, {"steps": 101}]
)
def test_demo_parameters_are_bounded(client, body):
    assert client.post("/api/demo", json=body).status_code == 422
    assert client.get("/api/runs").json() == []


def test_cross_origin_and_form_writes_are_rejected(client):
    response = client.post("/api/demo", json={}, headers={"Origin": "https://unrelated.example"})
    assert response.status_code == 403
    assert client.post("/api/demo", data={"steps": "4"}).status_code == 415
    response = client.post(
        "/api/demo", json={"scenario": "clean", "steps": 1}, headers={"Origin": "http://127.0.0.1"}
    )
    assert response.status_code == 201


def test_request_body_is_bounded(client):
    response = client.post("/api/demo", json={"unused": "x" * 65536})
    assert response.status_code == 413
    assert client.get("/api/runs").json() == []


def test_untrusted_host_is_rejected(client):
    response = client.get("/api/runs", headers={"Host": "attacker.example"})
    assert response.status_code == 400
