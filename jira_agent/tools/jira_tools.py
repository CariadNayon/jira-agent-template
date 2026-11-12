"""Eingebaute Jira-Tools. Vorlage für eigene Tools: example_custom_tool.py."""
from __future__ import annotations

import re
import time

from jira_agent.jira_client import JiraClient
from jira_agent.tools import ToolContext, tool

_FIELDS = "summary,status,priority,components,assignee,updated"
CHAT_MAX_RESULTS = 50      # Treffer pro Suche im Chat
EXPORT_PAGE_SIZE = 100     # Treffer pro Jira-API-Seite


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


def search_issues(jira: JiraClient, jql: str, max_results: int, start_at: int = 0) -> dict:
    data = jira.search(jql, max_results, fields=_FIELDS, start_at=start_at)
    issues = [summarize_issue(i) for i in data.get("issues", [])]
    total = data.get("total")
    more = total is None or start_at+len(issues) < total
    return {"total":total,"issues":issues,"truncated":more,
            "next_start_at":start_at+len(issues) if more and issues else None}


def export_issues(jira: JiraClient, jql: str, limit: int, start_at: int = 0, timeout: float = 60) -> dict:
    """Read every page up to a documented cap, respecting server-side page-size limits."""
    if limit < 1 or start_at < 0:
        raise ValueError("Export-Limit muss positiv sein; start_at darf nicht negativ sein.")
    query = jql if re.search(r'\border\s+by\b',jql,re.I) else jql.rstrip()+' ORDER BY key ASC'
    issues, seen, offset, total, reason = [], set(), start_at, None, ''
    deadline=time.monotonic()+timeout
    while len(issues)<limit:
        if time.monotonic()>=deadline:
            reason='Zeitlimit erreicht. Der Export ist unvollständig.';break
        data=jira.search(query,min(EXPORT_PAGE_SIZE,limit-len(issues)),fields=_FIELDS,start_at=offset)
        current=data.get('total')
        if not isinstance(current,int) or current<0:
            reason='Jira meldet keine verlässliche Gesamtzahl. Vollständigkeit ist nicht bestätigt.';break
        if total is None:total=current
        elif current!=total:
            reason='Die Jira-Treffermenge hat sich während des Exports verändert. Bitte erneut abfragen.';break
        if data.get('startAt',offset)!=offset:
            reason='Jira hat die angeforderte Ergebnisseite nicht geliefert.';break
        page=data.get('issues',[])
        if not page:
            if offset<total:reason='Jira lieferte vorzeitig eine leere Ergebnisseite.'
            break
        keys=[i.get('key') for i in page]
        if None in keys or len(set(keys))!=len(keys) or seen.intersection(keys):
            reason='Jira lieferte doppelte oder ungültige Treffer. Vollständigkeit ist nicht bestätigt.';break
        if len(page)>limit-len(issues):
            page=page[:limit-len(issues)];keys=[i['key'] for i in page]
        seen.update(keys)
        issues.extend(summarize_issue(i) for i in page)
        offset+=len(page)
        if offset>=total:break
    truncated=bool(reason) or total is None or offset<total
    if truncated and not reason:reason=f'Export-Limit von {limit} Tickets erreicht. Filter eingrenzen oder mit next_start_at fortsetzen.'
    return {'total':total,'issues':issues,'truncated':truncated,'start_at':start_at,
            'next_start_at':offset if truncated else None,'warning':reason,
            'query':query,'snapshot':False}



@tool(needs=["jira"])
def jira_search(ctx: ToolContext, jql: str, max_results: int = 20, start_at: int = 0) -> dict:
    """Sucht Jira-Tickets per JQL, z. B. 'assignee = currentUser() ORDER BY updated DESC'.

    jql: JQL-Abfrage
    max_results: maximale Anzahl Treffer (höchstens 50)
    start_at: Ergebnisposition ab 0; next_start_at zum Weiterblättern nutzen
    """
    return search_issues(ctx.jira, jql, max(1,min(int(max_results), CHAT_MAX_RESULTS)), start_at)


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
