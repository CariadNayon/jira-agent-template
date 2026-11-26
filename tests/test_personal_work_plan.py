"""Regression: personal Jira planning is scoped and complete, without global CR aggregation."""
from jira_agent.testing import FakeJira, run_tool
from jira_agent.tools import load_tools
from jira_agent.runtime import JIRA_GUIDANCE


def test_personal_plan_fetches_complete_own_work_and_prioritizes():
    jira = FakeJira(issues={
        "DEMO-1": {"summary": "Minor task", "priority": "Minor"},
        "DEMO-2": {"summary": "Major task", "priority": "Major"},
        "DEMO-3": {"summary": "Critical task", "priority": "Critical"},
    })
    result = run_tool("jira_plan_my_work", jira=jira)
    assert result["complete"] is True
    assert result["total"] == result["processed"] == 3
    assert [i["key"] for i in result["ranked_issues"]] == ["DEMO-3", "DEMO-2", "DEMO-1"]
    assert result["query"].startswith("assignee = currentUser() AND resolution IS EMPTY")
    assert "unknown" in result["ranked_issues"][-1]["effort"]
    assert not any("Change Request" in str(call) for call in jira.calls)


def test_personal_plan_safe_limit():
    jira = FakeJira(issues={"DEMO-1": {}})
    assert run_tool("jira_plan_my_work", jira=jira, max_issues=0)["error"] == "ValueError"
    assert run_tool("jira_plan_my_work", jira=jira, max_issues=101)["error"] == "ValueError"
    assert not jira.calls


def test_plan_is_available_and_guidance_prefers_it():
    assert "jira_plan_my_work" in load_tools()
    assert "ALWAYS prefer" in JIRA_GUIDANCE
