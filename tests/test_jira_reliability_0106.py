"""End-to-end log regressions: @me JQL, Jira rate limits, and verified age guidance."""
from jira_agent.jira_client import JiraError
from jira_agent.runtime import JIRA_GUIDANCE
from jira_agent.testing import FakeJira, run_tool


def test_advanced_search_normalizes_assignee_me_without_identity_lookup():
    jira = FakeJira(issues={"ABC-1": {"summary": "Test"}})
    result = run_tool("jira_search", jira=jira,
                      jql='issuetype = "Change Request" AND assignee = @me AND resolution IS EMPTY ORDER BY priority DESC')
    assert "assignee = currentUser()" in result["query"]
    assert "@me" not in jira.calls[0][2]["jql"]
    assert all(path != "/myself" for _, path, _ in jira.calls)


def test_advanced_search_preserves_other_jql():
    jira = FakeJira()
    jql = 'text ~ "\"assigned to @me\"" ORDER BY created DESC'
    result = run_tool("jira_search", jira=jira, jql=jql)
    assert result["query"] == jql


def test_cr_breakdown_returns_incomplete_on_first_page_429():
    class LimitedJira(FakeJira):
        def search(self, *args, **kwargs):
            raise JiraError("Rate limited", status_code=429)

    result = run_tool("jira_breakdown_change_requests", jira=LimitedJira())
    assert result["complete"] is False
    assert result["processed"] == result["group_sum"] == 0
    assert result["jira_total"] is None
    assert "429" in result["warning"]


def test_cr_breakdown_keeps_verified_partial_results_after_429():
    class LimitedJira(FakeJira):
        def search(self, *args, **kwargs):
            if kwargs.get("start_at", 0) >= 100:
                raise JiraError("Rate limited", status_code=429)
            return super().search(*args, **kwargs)

    jira = LimitedJira(issues={f"ABC-{i}": {"status": "Open", "priority": "Major"} for i in range(1, 106)})
    result = run_tool("jira_breakdown_change_requests", jira=jira, max_issues=105)
    assert result["complete"] is False
    assert result["jira_total"] == 105
    assert result["processed"] == result["group_sum"] == 100
    assert "429" in result["warning"]


def test_guidance_uses_python_age_and_distinguishes_preview():
    assert "NEVER" in JIRA_GUIDANCE and "manually approximate" in JIRA_GUIDANCE
    assert "requested_count from jira_total" in JIRA_GUIDANCE
