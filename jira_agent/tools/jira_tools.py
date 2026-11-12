"""Eingebaute Jira-Tools."""
from __future__ import annotations

from jira_agent.jira_client import JiraClient
from jira_agent.tools import ToolContext, tool

_FIELDS = "summary,status,priority,components,assignee,updated"


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
    r = jira.request("GET", "/search", params={
        "jql": jql, "maxResults": max(1, min(int(max_results), 100)), "fields": _FIELDS})
    if r.status_code != 200:
        return _error(r)
    data = r.json()
    return {"total": data.get("total"), "issues": [summarize_issue(i) for i in data.get("issues", [])]}


def _error(r) -> dict:
    return {"error": r.status_code, "details": r.text[:500]}


@tool("Sucht Jira-Tickets per JQL, z. B. 'assignee = currentUser() ORDER BY updated DESC'.",
      {"jql": {"type": "string"}, "max_results": {"type": "integer"}}, ["jql"], needs=["jira"])
def jira_search(ctx: ToolContext, jql: str, max_results: int = 20) -> dict:
    return search_issues(ctx.jira, jql, min(int(max_results), 50))


@tool("Liefert Details und Beschreibung eines Tickets.",
      {"issue_key": {"type": "string"}}, ["issue_key"], needs=["jira"])
def jira_get_issue(ctx: ToolContext, issue_key: str) -> dict:
    key = JiraClient.check_key(issue_key)
    r = ctx.jira.request("GET", f"/issue/{key}", params={
        "fields": "summary,description,status,priority,components,assignee,labels,updated"})
    if r.status_code != 200:
        return _error(r)
    issue = r.json()
    out = summarize_issue(issue)
    out["labels"] = issue.get("fields", {}).get("labels")
    out["description"] = (issue.get("fields", {}).get("description") or "")[:3000]
    return out


@tool("Sucht Jira-Nutzer nach Name oder Kennung.",
      {"query": {"type": "string"}}, ["query"], needs=["jira"])
def jira_find_user(ctx: ToolContext, query: str) -> dict:
    r = ctx.jira.request("GET", "/user/search", params={"username": query, "maxResults": 10})
    if r.status_code != 200:
        return _error(r)
    return {"users": [{"name": u.get("name"), "displayName": u.get("displayName")} for u in r.json()]}


@tool("Leitet ein Ticket an einen Nutzer weiter (Bearbeiter setzen).",
      {"issue_key": {"type": "string"}, "user_name": {"type": "string"}},
      ["issue_key", "user_name"], write=True, needs=["jira"])
def jira_assign(ctx: ToolContext, issue_key: str, user_name: str) -> dict:
    key, user = JiraClient.check_key(issue_key), JiraClient.check_user(user_name)
    r = ctx.jira.request("PUT", f"/issue/{key}/assignee", json={"name": user})
    return {"status": "OK"} if r.status_code == 204 else _error(r)


@tool("Schreibt einen Kommentar in ein Ticket.",
      {"issue_key": {"type": "string"}, "text": {"type": "string"}},
      ["issue_key", "text"], write=True, needs=["jira"])
def jira_comment(ctx: ToolContext, issue_key: str, text: str) -> dict:
    key = JiraClient.check_key(issue_key)
    r = ctx.jira.request("POST", f"/issue/{key}/comment", json={"body": text})
    return {"status": "OK"} if r.status_code == 201 else _error(r)
