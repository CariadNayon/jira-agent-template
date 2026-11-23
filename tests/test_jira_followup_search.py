"""Regression tests for Jira issue details and compact aggregation."""
from jira_agent.testing import FakeJira, run_tool
from jira_agent.runtime import JIRA_GUIDANCE


def test_issue_details_expose_created_resolution_and_type():
    jira = FakeJira(issues={"ABC-1": {"created": "2016-09-15T10:28:20+0200",
        "status": "Closed", "issue_type": "Change Request",
        "resolution": "Done", "fix_versions": ["CL8.21"]}})
    result = run_tool("jira_get_issue", jira=jira, issue_key="ABC-1")
    assert result["created"] == "2016-09-15T10:28:20+0200"
    assert result["age_days"] is not None
    assert result["issue_type"] == "Change Request"
    assert result["resolution"] == "Done"
    assert result["fix_versions"] == ["CL8.21"]
    fields = jira.calls[0][2]["fields"]
    assert all(f in fields for f in ("created", "resolution", "issuetype", "fixVersions"))


def test_breakdown_sums_match_total():
    jira = FakeJira(issues={
        "ABC-1": {"status": "Open", "priority": "Major"},
        "ABC-2": {"status": "Done", "priority": "Minor"},
        "ABC-3": {"status": "Open", "priority": "Major"}})
    result = run_tool("jira_breakdown_change_requests", jira=jira)
    assert result["complete"] is True
    assert result["jira_total"] == result["processed"] == result["group_sum"] == 3
    assert result["by_status"] == {"Done": 1, "Open": 2}
    assert result["by_priority"] == {"Major": 2, "Minor": 1}


def test_breakdown_limit_marks_partial():
    jira = FakeJira(issues={f"ABC-{i}": {"status": "Open"} for i in range(1, 5)})
    result = run_tool("jira_breakdown_change_requests", jira=jira, max_issues=2)
    assert result["complete"] is False
    assert result["jira_total"] == 4
    assert result["processed"] == result["group_sum"] == 2
    assert "Export limit" in result["warning"]


def test_breakdown_invalid_limit_rejected_before_jira():
    jira = FakeJira()
    result = run_tool("jira_breakdown_change_requests", jira=jira, max_issues=0)
    assert result["error"] == "ValueError"
    assert not jira.calls


def test_guidance_defends_against_wrong_tool_selection():
    assert "jira_breakdown_change_requests" in JIRA_GUIDANCE
    assert 'text="[J09]"' in JIRA_GUIDANCE
    assert "assignee = currentUser()" in JIRA_GUIDANCE
