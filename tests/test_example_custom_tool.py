"""Vorlage: So testen Sie ein eigenes Tool – ohne echtes Jira.

Kopieren, Tool-Namen und Argumente anpassen, dann: uv run pytest tests -q
"""
from jira_agent.testing import FakeJira, run_tool


def test_label_wird_gesetzt():
    jira = FakeJira(issues={"ABC-1": {"summary": "Bremse quietscht"}})

    result = run_tool("jira_add_label", jira=jira, issue_key="ABC-1", label="geprueft")

    assert result == {"status": "OK"}
    assert jira.issues["ABC-1"]["labels"] == ["geprueft"]


def test_schreib_tool_fragt_ohne_bestaetigung_nach():
    jira = FakeJira(issues={"ABC-1": {}})

    result = run_tool("jira_add_label", jira=jira, confirm=False, issue_key="ABC-1", label="geprueft")

    assert result["status"] == "BESTAETIGUNG_NOETIG"
    assert jira.issues["ABC-1"]["labels"] == []


def test_ungueltiges_label_gibt_fehler():
    result = run_tool("jira_add_label", jira=FakeJira(issues={"ABC-1": {}}), issue_key="ABC-1", label="mit leerzeichen")

    assert result["error"] == "ValueError"
