"""Smoke tests for the Python-only developer app.

No real Jira, model, MLflow server, Databricks login or Node frontend required.
"""
import os
from pathlib import Path

from fastapi.testclient import TestClient


def test_start_local_does_not_reference_node_or_mlflow_agentserver():
    from scripts import start_local
    source = Path(start_local.__file__).read_text(encoding="utf-8")
    assert 'uvicorn.run("local_app.server:app"' in source
    assert 'host="127.0.0.1"' in source
    assert "subprocess" not in source


def test_local_ui_and_health(monkeypatch):
    monkeypatch.setenv("JIRA_AGENT_LOCAL_MODE", "1")
    monkeypatch.delenv("DATABRICKS_APP_NAME", raising=False)
    monkeypatch.delenv("DATABRICKS_RUNTIME_VERSION", raising=False)
    from local_app.server import app
    with TestClient(app) as c:
        health = c.get("/health")
        assert health.status_code == 200
        assert health.json()["mode"] == "local-fastapi"
        page = c.get("/")
        assert page.status_code == 200
        assert "Connect Jira" in page.text
        assert "LOCAL FASTAPI" in page.text
        me = c.get("/jira/api/me")
        assert me.status_code == 200
        assert me.json()["email"] == "local"


def test_local_origin_and_json_only_enforced(monkeypatch):
    monkeypatch.setenv("JIRA_AGENT_LOCAL_MODE", "1")
    from local_app.server import app
    with TestClient(app, base_url="http://127.0.0.1:8000") as c:
        denied = c.post(
            "/api/local/reset", json={},
            headers={"origin": "https://evil.example"}
        )
        assert denied.status_code == 403
        form = c.post(
            "/api/local/reset", data={"test": "x"},
            headers={"content-type": "application/x-www-form-urlencoded"}
        )
        assert form.status_code == 415
        accepted = c.post(
            "/api/local/reset", json={},
            headers={"origin": "http://127.0.0.1:8000"}
        )
        assert accepted.status_code == 200


def test_hosted_environment_does_not_use_local_identity(monkeypatch):
    monkeypatch.setenv("JIRA_AGENT_LOCAL_MODE", "1")
    monkeypatch.setenv("DATABRICKS_APP_NAME", "hosted-agent")
    from jira_agent.runtime import identity, local_mode_active
    assert not local_mode_active()
    assert identity({}) == (None, None)
