"""Compact read-only personal work planning with guaranteed Jira assignee scope."""
from __future__ import annotations

from jira_agent.tools import ToolContext, tool
from jira_agent.tools.jira_tools import export_issues

_PRIORITY = {
    "highest": 0, "blocker": 0, "critical": 1, "high": 2, "major": 2,
    "medium": 3, "normal": 3, "minor": 4, "low": 4, "lowest": 5, "trivial": 5,
}


@tool(needs=["jira"])
def jira_plan_my_work(ctx: ToolContext, max_issues: int = 100) -> dict:
    """Get ALL currently assigned unresolved Jira tickets and a provisional priority-ranked work list.
    Prefer this for 'what do I have to do', 'break down my tickets', 'prioritize my tasks',
    and 'give me next steps' including their follow-ups. Always scoped to the connected user.
    Does not assume issue type or invent effort, due dates, or urgency.

    max_issues: maximum personal tickets to inspect, between 1 and 100 (default 100)
    """
    if not 1 <= int(max_issues) <= 100:
        raise ValueError("max_issues must be between 1 and 100.")
    query = "assignee = currentUser() AND resolution IS EMPTY"
    result = export_issues(ctx.jira, query, limit=int(max_issues), timeout=25)
    issues = sorted(result["issues"], key=lambda item: (
        _PRIORITY.get(str(item.get("priority") or "").casefold(), 6),
        str(item.get("key") or ""),
    ))
    for issue in issues:
        issue["effort"] = "unknown (not returned by this Jira search)"
        issue["urgency"] = "not independently verified; Jira priority is only a proxy"
        issue["next_step"] = "Review the ticket description, acceptance criteria and blockers; determine the next concrete action."
    return {
        "scope": "Only unresolved Jira issues assigned to the signed-in user",
        "query": result["query"],
        "total": result["total"],
        "processed": len(issues),
        "complete": not result["truncated"],
        "ranked_issues": issues,
        "ranking_method": "Provisional Jira priority order; this is not a verified effort, business importance or deadline ranking",
        "warning": result["warning"],
        "instruction": "Present a concrete numbered to-do list with the available ticket keys, titles and statuses. "
                       "Do not ask the user to confirm the already established scope. "
                       "When effort is unknown, still give a useful provisional plan; label unknown estimates.",
    }
