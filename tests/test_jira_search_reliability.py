"""Regression tests for Jira search reliability and stress-test failures."""
import pytest

from jira_agent.testing import FakeJira, run_tool
from jira_agent.runtime import JIRA_GUIDANCE


def test_plain_text_search_rejects_jql_issue_type():
    jira = FakeJira(issues={"ABC-1": {"summary": "Change request"}})
    with pytest.raises(ValueError, match="not JQL"):
        run_tool("jira_search_tickets", jira=jira, text='issuetype="Change Request"')
    assert jira.calls == []


def test_plain_text_search_rejects_jql_fix_version():
    jira = FakeJira()
    with pytest.raises(ValueError, match="not JQL"):
        run_tool("jira_search_tickets", jira=jira, text="fixVersion=CL8.21")
    assert jira.calls == []


def test_plain_text_search_allows_plain_words():
    jira = FakeJira(issues={"ABC-1": {"summary": "Brake fault"}})
    result = run_tool("jira_search_tickets", jira=jira, text="brake fault")
    assert result["query"].startswith('text ~ ')
    assert len(result["issues"]) == 1


def test_advanced_jql_preserved_and_shows_query():
    jira = FakeJira(issues={"ABC-1": {"summary": "Brake fault", "created": "2026-01-01T00:00:00Z"}})
    query = 'project = ABC AND resolution IS EMPTY ORDER BY created ASC'
    result = run_tool("jira_search", jira=jira, jql=query)
    assert result["query"] == query
    assert jira.calls[0][2]["jql"] == query
    assert result["issues"][0]["created"] == "2026-01-01T00:00:00Z"


def test_search_exposes_resolution_and_issue_type():
    jira = FakeJira(issues={"ABC-1": {"summary": "Change", "resolution": "Fixed", "issue_type": "Change Request",
                                      "fix_versions": ["CL8.21"]}})
    result = run_tool("jira_search", jira=jira, jql="project = ABC")
    issue = result["issues"][0]
    assert "resolution" in issue
    assert "issue_type" in issue
    assert "fix_versions" in issue


def test_search_requires_valid_total():
    class MissingTotalJira:
        def search(self, *args, **kwargs):
            return {"issues": [], "startAt": 0}

    with pytest.raises(ValueError, match="reliable issue count"):
        run_tool("jira_search", jira=MissingTotalJira(), jql="project = ABC")


def test_search_rejects_mismatched_page():
    class WrongPageJira:
        def search(self, *args, **kwargs):
            return {"issues": [], "total": 5, "startAt": 0}

    with pytest.raises(ValueError, match="unexpected results page"):
        run_tool("jira_search", jira=WrongPageJira(), jql="project = ABC", start_at=2)


def test_guidance_includes_stress_test_guards():
    assert "NEVER a project key" in JIRA_GUIDANCE
    assert "never JQL" in JIRA_GUIDANCE
    assert "ORDER BY created ASC" in JIRA_GUIDANCE
    assert "Never invent a SQL table" in JIRA_GUIDANCE
