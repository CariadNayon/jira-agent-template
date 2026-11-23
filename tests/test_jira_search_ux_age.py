"""Regression tests for deterministic Jira age calculations and project discovery."""
from datetime import datetime, timezone

from jira_agent.testing import FakeJira, run_tool
from jira_agent.tools.jira_tools import summarize_issue
from jira_agent.runtime import JIRA_GUIDANCE


def test_age_is_computed_from_utc_dates_not_model_arithmetic():
    issue = {"key": "ABC-1", "fields": {"created": "2016-09-16T10:35:00.000+0200"}}
    result = summarize_issue(issue, now=datetime(2026, 11, 23, 8, tzinfo=timezone.utc))
    assert result["age_days"] == (datetime(2026, 11, 23).date() - datetime(2016, 9, 16).date()).days


def test_age_handles_timezone_crossing_midnight():
    issue = {"key": "ABC-2", "fields": {"created": "2026-11-22T23:45:00-0200"}}
    result = summarize_issue(issue, now=datetime(2026, 11, 23, 15, tzinfo=timezone.utc))
    assert result["age_days"] == 0


def test_age_invalid_and_future_timestamps_are_not_invented():
    now = datetime(2026, 11, 23, tzinfo=timezone.utc)
    assert summarize_issue({"key": "A-1", "fields": {}}, now=now)["age_days"] is None
    assert summarize_issue({"key": "A-2", "fields": {"created": "not-a-date"}}, now=now)["age_days"] is None
    assert summarize_issue({"key": "A-3", "fields": {"created": "2027-01-01T00:00:00Z"}}, now=now)["age_days"] is None


def test_search_without_project_uses_all_accessible_jira_issues():
    jira = FakeJira(issues={"AAA-1": {}, "BBB-1": {}})
    result = run_tool("jira_search", jira=jira, jql="resolution IS EMPTY ORDER BY created ASC")
    assert result["total"] == 2
    assert "project" not in result["query"].lower()


def test_project_search_falls_back_to_partial_name_suggestions():
    class NamedProjects(FakeJira):
        def projects(self):
            return [
                {"key": "CMOD", "name": "Conmod Platform"},
                {"key": "PPE", "name": "PPE Control"},
                {"key": "OTHER", "name": "Other"},
            ]

    result = run_tool("jira_list_projects", jira=NamedProjects(), query="Conmod PPE")
    assert result["approximate_matches"] is True
    assert {p["key"] for p in result["projects"]} == {"CMOD", "PPE"}
    assert "confirm" in result["hint"]


def test_exact_project_search_remains_precise():
    class NamedProjects(FakeJira):
        def projects(self):
            return [
                {"key": "PPE", "name": "Conmod PPE"},
                {"key": "PPE2", "name": "Conmod Alternative"},
            ]

    result = run_tool("jira_list_projects", jira=NamedProjects(), query="Conmod PPE")
    assert result["approximate_matches"] is False
    assert [p["key"] for p in result["projects"]] == ["PPE"]


def test_guidance_keeps_project_optional_for_readonly_search():
    assert "read-only Jira search specifies no project" in JIRA_GUIDANCE
    assert "age_days returned by the Python Jira tool" in JIRA_GUIDANCE
