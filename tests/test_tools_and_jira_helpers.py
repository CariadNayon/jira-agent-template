"""Tests für @tool (Schema aus Type-Hints/Docstring) und die Jira-Helfer des JiraClient."""
from typing import Literal, Optional

import pytest

from jira_agent.jira_client import JiraError
from jira_agent.testing import FakeJira, run_tool
from jira_agent.tools import infer_schema


def test_infer_schema_from_hints_and_docstring():
    def beispiel(ctx, key: str, modus: Literal["a", "b"], tags: list[str], anzahl: int = 5,
                 notiz: Optional[str] = None) -> dict:
        """Macht etwas Nützliches.
        Zweite Zeile der Beschreibung.

        Args:
            key: Ticket-Key,
                z. B. ABC-1
            modus: Modus
        """

    desc, props, required = infer_schema(beispiel)
    assert desc == "Macht etwas Nützliches.\nZweite Zeile der Beschreibung."
    assert props["key"] == {"type": "string", "description": "Ticket-Key, z. B. ABC-1"}
    assert props["modus"] == {"type": "string", "enum": ["a", "b"], "description": "Modus"}
    assert props["tags"] == {"type": "array", "items": {"type": "string"}}
    assert props["anzahl"] == {"type": "integer"} and props["notiz"] == {"type": "string"}
    assert required == ("key", "modus", "tags")


def test_helpers_change_fake_jira():
    jira = FakeJira(issues={"ABC-1": {}, "ABC-2": {}})

    new_key = jira.create_issue("abc", "Neues Ticket", priority="High", components=["Bremse"])
    jira.transition("ABC-1", "erledigt", comment="fertig")
    jira.set_priority("ABC-1", "Low")
    jira.link("ABC-1", "ABC-2", "Blocks")
    jira.add_worklog("ABC-1", "1h 30m")

    assert new_key == "ABC-3"
    assert jira.issues["ABC-3"]["fields"]["priority"] == {"name": "High"}
    assert jira.issues["ABC-3"]["fields"]["components"] == [{"name": "Bremse"}]
    assert jira.issues["ABC-1"]["status"] == "Erledigt"
    assert jira.calls[-4][2]["update"] == {"comment": [{"add": {"body": "fertig"}}]}
    assert jira.issues["ABC-1"]["priority"] == "Low"
    assert jira.issues["ABC-1"]["links"] == [("Blocks", "ABC-2")]
    assert jira.issues["ABC-1"]["worklogs"] == ["1h 30m"]


def test_helper_errors_are_readable():
    jira = FakeJira(issues={"ABC-1": {}})
    with pytest.raises(JiraError, match="nicht möglich.*Start"):
        jira.transition("ABC-1", "Gibt es nicht")
    with pytest.raises(JiraError, match="HTTP 404"):
        jira.comment("ABC-9", "x")


def test_builtin_tools_use_helpers():
    jira = FakeJira(issues={"ABC-1": {"summary": "Laden defekt"}})

    assert run_tool("jira_assign", jira=jira, issue_key="ABC-1", user_name="energy.lead") == {"status": "OK"}
    assert run_tool("jira_search", jira=jira, jql="project = ABC")["issues"][0]["assignee"] == "energy.lead"
    assert run_tool("jira_assign", jira=jira, issue_key="ABC-1", user_name="x y")["error"] == "ValueError"


def test_runtime_falls_back_to_databricks_yml_defaults(monkeypatch):
    import importlib

    import jira_agent.runtime as runtime
    from jira_agent import BUNDLE

    assert {"app_name", "secret_scope", "secret_key", "warehouse_id"} <= BUNDLE.keys()
    assert all(BUNDLE[k] for k in ("app_name", "secret_scope", "secret_key", "warehouse_id"))
    monkeypatch.delenv("WAREHOUSE_ID", raising=False)
    assert importlib.reload(runtime).WAREHOUSE_ID == BUNDLE["warehouse_id"]
    monkeypatch.setenv("WAREHOUSE_ID", "from-app-resource")
    assert importlib.reload(runtime).WAREHOUSE_ID == "from-app-resource"
