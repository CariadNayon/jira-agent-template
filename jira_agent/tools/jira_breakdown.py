"""Compact read-only Jira aggregations; never return thousands of issues to the language model."""
from __future__ import annotations

from collections import Counter

from jira_agent.tools import ToolContext, tool
from jira_agent.tools.jira_tools import export_issues


@tool(needs=["jira"])
def jira_breakdown_change_requests(ctx: ToolContext, max_issues: int = 20000) -> dict:
    """Count Change Requests by Jira status and priority across all accessible projects.
    Pages through Jira server-side; returns compact counts, not the whole issue list.
    Results are complete only if every Jira result page is verified. Never use SQL for this.

    max_issues: maximum number of Jira issues to inspect, 1 to 20000; completeness is reported"""
    if not 1 <= int(max_issues) <= 20000:
        raise ValueError("max_issues must be between 1 and 20000.")
    result = export_issues(ctx.jira, 'issuetype = "Change Request"', limit=int(max_issues), timeout=90)
    issues = result["issues"]
    statuses = Counter((issue.get("status") or "(empty)") for issue in issues)
    priorities = Counter((issue.get("priority") or "(empty)") for issue in issues)
    combined = Counter(((issue.get("status") or "(empty)"), (issue.get("priority") or "(empty)")) for issue in issues)
    complete = not result["truncated"] and result["total"] == len(issues)
    return {
        "jql": result["query"],
        "jira_total": result["total"],
        "processed": len(issues),
        "complete": complete,
        "by_status": dict(sorted(statuses.items())),
        "by_priority": dict(sorted(priorities.items())),
        "by_status_and_priority": [
            {"status": status, "priority": priority, "count": count}
            for (status, priority), count in sorted(combined.items())
        ],
        "group_sum": sum(combined.values()),
        "warning": result["warning"] if not complete else "",
    }
