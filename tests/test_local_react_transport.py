"""React AI SDK v6 transport compatibility without external Jira/model calls."""
import json

from fastapi.testclient import TestClient

from local_app.react_api import _frame, _user_text


def test_react_message_text_conversion():
    assert _user_text({
        "role": "user",
        "parts": [{"type": "text", "text": "My open Jira tickets"},
                  {"type": "file", "url": "data:fake"},
                  {"type": "text", "text": "/show-ticket"}]
    }) == "My open Jira tickets\n/show-ticket"
    assert _user_text({"role": "assistant", "parts": [{"type": "text", "text": "no"}]}) == ""


def test_ai_sdk_sse_protocol():
    part = {"type": "text-delta", "id": "abc", "delta": "Hi there"}
    assert _frame(part) == "data: " + json.dumps(part, separators=(",", ":")) + "\n\n"


def test_react_session_config_and_bad_chat_request(monkeypatch):
    monkeypatch.setenv("JIRA_AGENT_LOCAL_MODE", "1")
    monkeypatch.delenv("DATABRICKS_APP_NAME", raising=False)
    monkeypatch.delenv("DATABRICKS_RUNTIME_VERSION", raising=False)
    from local_app.server import app
    with TestClient(app, base_url="http://127.0.0.1:8000") as client:
        assert client.get("/api/session").json()["user"]["email"] == "local"
        assert client.get("/api/config").json()["features"]["chatHistory"] is False
        assert client.get("/api/history").status_code == 204
        assert client.get("/api/chat/any/stream").status_code == 204
        # Invalid payload must be rejected before calling Jira/Azure model.
        assert client.post("/api/chat", json={"id": "abc", "message": {}}).status_code == 400
