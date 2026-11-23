"""Eingebaute Jira-Tools. Vorlage für eigene Tools: example_custom_tool.py."""
from __future__ import annotations

import re
import time
from datetime import datetime, timezone

from jira_agent.jira_client import JiraClient, JiraError
from jira_agent.tools import ToolContext, tool

_FIELDS = "summary,status,priority,components,assignee,updated,created,resolution,issuetype,fixVersions"
CHAT_MAX_RESULTS = 50      # Treffer pro Suche im Chat
EXPORT_PAGE_SIZE = 100     # Treffer pro Jira-API-Seite


def summarize_issue(issue: dict, *, now: datetime | None = None) -> dict:
    f = issue.get("fields", {})
    created = f.get("created")
    age_days = None
    if isinstance(created, str):
        try:
            parsed = datetime.fromisoformat(created.replace("Z", "+00:00"))
            if parsed.tzinfo is not None:
                today = (now or datetime.now(timezone.utc)).astimezone(timezone.utc).date()
                age_days = (today - parsed.astimezone(timezone.utc).date()).days
                if age_days < 0:
                    age_days = None
        except ValueError:
            pass
    return {
        "key": issue.get("key"),
        "summary": f.get("summary"),
        "status": (f.get("status") or {}).get("name"),
        "priority": (f.get("priority") or {}).get("name"),
        "components": [c.get("name") for c in f.get("components") or []],
        "assignee": (f.get("assignee") or {}).get("name"),
        "updated": f.get("updated"),
        "created": created,
        "age_days": age_days,
        "resolution": (f.get("resolution") or {}).get("name"),
        "issue_type": (f.get("issuetype") or {}).get("name"),
        "fix_versions": [v.get("name") for v in f.get("fixVersions") or []],
    }


def search_issues(jira: JiraClient, jql: str, max_results: int, start_at: int = 0) -> dict:
    data = jira.search(jql, max_results, fields=_FIELDS, start_at=start_at)
    if not isinstance(data.get("total"), int) or data["total"] < 0:
        raise ValueError("Jira did not return a reliable issue count.")
    if data.get("startAt", start_at) != start_at:
        raise ValueError("Jira returned an unexpected results page.")
    issues = [summarize_issue(i) for i in data.get("issues", [])]
    total = data.get("total")
    more = total is None or start_at+len(issues) < total
    return {"total":total,"issues":issues,"truncated":more,
            "next_start_at":start_at+len(issues) if more and issues else None}


def export_issues(jira: JiraClient, jql: str, limit: int, start_at: int = 0, timeout: float = 60) -> dict:
    """Read every page up to a documented cap, respecting server-side page-size limits."""
    if limit < 1 or start_at < 0:
        raise ValueError("Export limit must be positive; start_at must not be negative.")
    query = jql if re.search(r'\border\s+by\b',jql,re.I) else jql.rstrip()+' ORDER BY key ASC'
    issues, seen, offset, total, reason = [], set(), start_at, None, ''
    deadline=time.monotonic()+timeout
    while len(issues)<limit:
        if time.monotonic()>=deadline:
            reason='Time limit reached. The export is incomplete.';break
        try:
            data=jira.search(query,min(EXPORT_PAGE_SIZE,limit-len(issues)),fields=_FIELDS,start_at=offset)
        except JiraError as exc:
            if exc.status_code == 429:
                reason='Jira rate limit exceeded (HTTP 429). The breakdown is incomplete; narrow the scope or retry later.'
                break
            raise
        current=data.get('total')
        if not isinstance(current,int) or current<0:
            reason='Jira did not report a reliable total. Completeness is unconfirmed.';break
        if total is None:total=current
        elif current!=total:
            reason='The Jira result set changed during the export. Please query again.';break
        if data.get('startAt',offset)!=offset:
            reason='Jira did not return the requested results page.';break
        page=data.get('issues',[])
        if not page:
            if offset<total:reason='Jira returned an empty results page too early.'
            break
        keys=[i.get('key') for i in page]
        if None in keys or len(set(keys))!=len(keys) or seen.intersection(keys):
            reason='Jira returned duplicate or invalid results. Completeness is unconfirmed.';break
        if len(page)>limit-len(issues):
            page=page[:limit-len(issues)];keys=[i['key'] for i in page]
        seen.update(keys)
        issues.extend(summarize_issue(i) for i in page)
        offset+=len(page)
        if offset>=total:break
    truncated=bool(reason) or total is None or offset<total
    if truncated and not reason:reason=f'Export limit of {limit} issues reached. Narrow the filter or continue with next_start_at.'
    return {'total':total,'issues':issues,'truncated':truncated,'start_at':start_at,
            'next_start_at':offset if truncated else None,'warning':reason,
            'query':query,'snapshot':False}



@tool(needs=["jira"])
def jira_search(ctx: ToolContext, jql: str, max_results: int = 20, start_at: int = 0) -> dict:
    """Searches Jira issues using JQL, e.g. 'assignee = currentUser() ORDER BY updated DESC'.
    Prefer jira_search_tickets for ordinary filters; use this tool for advanced user-supplied JQL.

    jql: JQL query
    max_results: maximum number of results (at most 50)
    start_at: zero-based result position; use next_start_at to continue"""
    if not isinstance(jql, str) or not jql.strip():
        raise ValueError("JQL must be a nonempty query string.")
    if start_at < 0:
        raise ValueError("start_at must not be negative.")
    # @me is a supported structured-search shortcut, not valid raw Jira JQL.
    # Resolve it only as the standalone assignee value, never inside quoted text.
    normalized_jql = re.sub(r"(?i)(\bassignee\s*=\s*)@me\b", r"\1currentUser()", jql)
    return {**search_issues(ctx.jira, normalized_jql, max(1,min(int(max_results), CHAT_MAX_RESULTS)), start_at), "query": normalized_jql}


@tool(needs=["jira"])
def jira_get_issue(ctx: ToolContext, issue_key: str) -> dict:
    """Returns issue details, the actual project and description. Use project.key to work in the same project.

    issue_key: issue key, e.g. ABC-123"""
    issue = ctx.jira.issue(issue_key, fields="project,summary,description,status,priority,components,assignee,labels,updated,created,resolution,issuetype,fixVersions")
    out = summarize_issue(issue)
    project = issue.get('fields', {}).get('project') or {}
    out['project'] = {'key': project.get('key'), 'name': project.get('name')}
    out["labels"] = issue.get("fields", {}).get("labels")
    out["description"] = (issue.get("fields", {}).get("description") or "")[:3000]
    out["url"] = ctx.jira.issue_url(issue_key)
    return out


@tool(needs=["jira"])
def jira_find_user(ctx: ToolContext, query: str) -> dict:
    """Searches Jira users by name or username.

    query: name or part of a username"""
    return {"users": ctx.jira.find_users(query)}


@tool(write=True, needs=["jira"])
def jira_assign(ctx: ToolContext, issue_key: str, user_name: str) -> dict:
    """Assigns an issue to a user.

    issue_key: issue key, e.g. ABC-123
    user_name: new assignee username (see jira_find_user), or @me for the connected Jira user"""
    ctx.jira.assign(issue_key, user_name)
    return {"status": "OK"}


@tool(write=True, needs=["jira"])
def jira_comment(ctx: ToolContext, issue_key: str, text: str) -> dict:
    """Adds a comment to an issue.

    issue_key: issue key, e.g. ABC-123
    text: comment text"""
    ctx.jira.comment(issue_key, text)
    return {"status": "OK"}
