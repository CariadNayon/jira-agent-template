"""Common ticket searches with fixed filters instead of model-authored JQL."""
from __future__ import annotations

import re
from typing import Literal

from jira_agent.jira_client import JiraClient
from jira_agent.write_outcome import InputValidationError
from jira_agent.tools import ToolContext, tool
from jira_agent.tools.jira_tools import CHAT_MAX_RESULTS, search_issues


def _quoted(value: str, *, max_length: int = 255) -> str:
    """Quote a JQL string value without allowing it to change the query structure."""
    if not isinstance(value, str) or len(value) > max_length or any(ord(c) < 32 for c in value):
        raise ValueError('Search values must be text, at most 255 characters and contain no control characters.')
    return '"' + value.replace('\\', '\\\\').replace('"', '\\"') + '"'


def _resolve_project(jira: JiraClient, project: str) -> str:
    """Accept valid keys or resolve an exact project name with the caller's Jira rights."""
    try:
        return JiraClient.check_project(project)
    except InputValidationError:
        matches = [p for p in jira.projects() if str(p.get('name') or '').casefold() == project.strip().casefold()]
        if len(matches) != 1 or not matches[0].get('key'):
            raise ValueError('Project name is unknown or ambiguous. Use jira_list_projects to select a key.')
        return JiraClient.check_project(matches[0]['key'])


@tool(needs=['jira'])
def jira_search_tickets(ctx: ToolContext, project: str = '', text: str = '', assignee: str = '',
                        state: Literal['any', 'open', 'resolved'] = 'any', status: str = '',
                        max_results: int = 10, start_at: int = 0) -> dict:
    """Search tickets using simple filters; preferred for ordinary searches without writing JQL.
    All filters are combined with AND. Empty filters mean any value. Results use the caller's Jira rights.
    Use jira_get_issue to show full details for a known key and jira_search for advanced JQL only.

    project: optional project key or exact project name; ambiguous names require clarification
    text: optional plain text phrase to find in issue text; not JQL or Lucene syntax
    assignee: Jira username, @me for the signed-in Jira user, @unassigned, or empty for anyone
    state: any, open (unresolved, including in progress), or resolved
    status: optional exact Jira status name; do not translate or invent status values
    max_results: result preview size, 1–50; use 1 for a requested example ticket
    start_at: zero-based position; continue with next_start_at from the previous result
    """
    if re.search(r'(?i)\b(?:issuetype|fixversion|resolution|created|updated|priority|project|assignee|status)\s*(?:=|!=|<=|>=|<|>|\bIS\b|\bIN\b)', text or '') or re.search(r'(?i)\b(?:ORDER\s+BY|AND|OR)\b', text or ''):
        raise ValueError('The text parameter accepts a plain text phrase, not JQL. Use jira_search(jql=...) for filters.')
    if state not in ('any', 'open', 'resolved'):
        raise ValueError('state must be any, open or resolved.')
    if start_at < 0:
        raise ValueError('start_at must not be negative.')
    conditions = []
    if project:
        conditions.append('project = ' + _quoted(_resolve_project(ctx.jira, project)))
    if text:
        _quoted(text)  # Validate before escaping the nested Lucene phrase.
        phrase = re.sub(r'([+\-&|!(){}\[\]^"~*?:\\/])', r'\\\1', text)
        conditions.append('text ~ ' + _quoted('"' + phrase + '"', max_length=1024))
    if assignee == '@me':
        conditions.append('assignee = currentUser()')
    elif assignee == '@unassigned':
        conditions.append('assignee IS EMPTY')
    elif assignee:
        conditions.append('assignee = ' + _quoted(JiraClient.check_user(assignee)))
    if state != 'any':
        conditions.append('resolution IS ' + ('EMPTY' if state == 'open' else 'NOT EMPTY'))
    if status:
        conditions.append('status = ' + _quoted(status))
    query = (' AND '.join(conditions) + ' ' if conditions else '') + 'ORDER BY updated DESC, key ASC'
    result = search_issues(ctx.jira, query, max(1, min(int(max_results), CHAT_MAX_RESULTS)), start_at)
    return {**result, 'query': query}
