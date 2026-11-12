"""Eingebaute Jira-Tools. Vorlage für eigene Tools: example_custom_tool.py."""
from __future__ import annotations

from jira_agent.jira_client import JiraClient
from jira_agent.tools import ToolContext, tool

_FIELDS = "summary,status,priority,components,assignee,updated"
CHAT_MAX_RESULTS = 50      # Treffer pro Suche im Chat
EXPORT_MAX_RESULTS = 100   # Treffer pro Export


def summarize_issue(issue: dict) -> dict:
    f = issue.get("fields", {})
    return {
        "key": issue.get("key"),
        "summary": f.get("summary"),
        "status": (f.get("status") or {}).get("name"),
        "priority": (f.get("priority") or {}).get("name"),
        "components": [c.get("name") for c in f.get("components") or []],
        "assignee": (f.get("assignee") or {}).get("name"),
        "updated": f.get("updated"),
    }


def search_issues(jira: JiraClient, jql: str, max_results: int) -> dict:
    data = jira.search(jql, max_results, fields=_FIELDS)
    return {"total": data.get("total"), "issues": [summarize_issue(i) for i in data.get("issues", [])]}


@tool(needs=["jira"])
def jira_search(ctx: ToolContext, jql: str, max_results: int = 20) -> dict:
    """Sucht Jira-Tickets per JQL, z. B. 'assignee = currentUser() ORDER BY updated DESC'.

    jql: JQL-Abfrage
    max_results: maximale Anzahl Treffer (höchstens 50)
    """
    return search_issues(ctx.jira, jql, min(int(max_results), CHAT_MAX_RESULTS))


@tool(needs=["jira"])
def jira_get_issue(ctx: ToolContext, issue_key: str) -> dict:
    """Liefert Details und Beschreibung eines Tickets.

    issue_key: Ticket-Key, z. B. ABC-123
    """
    issue = ctx.jira.issue(issue_key, fields="summary,description,status,priority,components,assignee,labels,updated")
    out = summarize_issue(issue)
    out["labels"] = issue.get("fields", {}).get("labels")
    out["description"] = (issue.get("fields", {}).get("description") or "")[:3000]
    return out


@tool(needs=["jira"])
def jira_find_user(ctx: ToolContext, query: str) -> dict:
    """Sucht Jira-Nutzer nach Name oder Kennung.

    query: Name oder Teil der Kennung
    """
    return {"users": ctx.jira.find_users(query)}


@tool(write=True, needs=["jira"])
def jira_assign(ctx: ToolContext, issue_key: str, user_name: str) -> dict:
    """Leitet ein Ticket an einen Nutzer weiter (Bearbeiter setzen).

    issue_key: Ticket-Key, z. B. ABC-123
    user_name: Jira-Kennung des neuen Bearbeiters (siehe jira_find_user) oder @me für den Jira-Benutzer
    """
    ctx.jira.assign(issue_key, user_name)
    return {"status": "OK"}


@tool(write=True, needs=["jira"])
def jira_comment(ctx: ToolContext, issue_key: str, text: str) -> dict:
    """Schreibt einen Kommentar in ein Ticket.

    issue_key: Ticket-Key, z. B. ABC-123
    text: Kommentartext
    """
    ctx.jira.comment(issue_key, text)
    return {"status": "OK"}
