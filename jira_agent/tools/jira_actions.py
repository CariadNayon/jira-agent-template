"""Wiederverwendbare Jira-Aktionen. Jede Änderung läuft durch dieselbe Bestätigungslogik.

Projektspezifische Abläufe gehören in skills/, zusätzliche Fähigkeiten in eigene Tool-Dateien.
Keine projektspezifischen Keys, Nutzer, Tickettypen oder Prioritäten hier fest einbauen.
"""
from __future__ import annotations

import re

from jira_agent.jira_client import JiraClient
from jira_agent.write_outcome import InputValidationError
from jira_agent.tools import ToolContext, tool


def _labels(labels: list[str]) -> list[str]:
    if not isinstance(labels, list) or any(not isinstance(x, str) or not re.fullmatch(r"[A-Za-z0-9_.-]{1,64}", x) for x in labels):
        raise InputValidationError("Labels: 1–64 characters, letters, digits, _ - . only.")
    return labels


@tool(write=True, needs=["jira"])
def jira_create_issue(ctx: ToolContext, project: str, summary: str, issue_type: str,
                      description: str = "", assignee: str = "", priority: str = "",
                      components: list[str] | None = None, labels: list[str] | None = None,
                      extra_fields: dict | None = None) -> dict:
    """Creates a Jira issue after user approval. First check the project, issue types and required fields
    with the metadata tools. Ask for missing information; never invent required values.

    project: confirmed project key
    summary: issue summary, at most 255 characters
    issue_type: actual issue type name from jira_list_issue_types
    description: issue description
    assignee: Jira username or @me for the connected Jira user; empty uses the project default
    priority: actual priority name; empty uses the project default
    components: component names from create metadata
    labels: labels without spaces
    extra_fields: additional Jira fields in API format from metadata, e.g. customfield_10010 or parent"""
    if extra_fields is not None and not isinstance(extra_fields, dict):
        raise InputValidationError('extra_fields must be an object with Jira field IDs.')
    if not isinstance(assignee, str) or not isinstance(priority, str) or not isinstance(description, str):
        raise InputValidationError('Assignee, priority and description must be strings.')
    if components is not None and (not isinstance(components, list) or
                                  any(not isinstance(c, str) or not c.strip() for c in components)):
        raise InputValidationError('Components must be a list of component names.')
    fields = dict(extra_fields or {})
    if set(fields) & {"project", "summary", "issuetype", "description", "assignee", "priority", "components", "labels"}:
        raise InputValidationError("Provide standard fields through their named parameters, not extra_fields.")
    if any(not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*", k) for k in fields):
        raise InputValidationError("Invalid field ID.")
    if assignee:
        fields["assignee"] = assignee
    if priority:
        fields["priority"] = priority
    if components is not None:
        fields["components"] = components
    if labels is not None:
        fields["labels"] = _labels(labels)
    key = ctx.jira.create_issue(project, summary, issue_type, description, **fields)
    return {"status": "OK", "key": key, "url": ctx.jira.issue_url(key)}


@tool(write=True, needs=["jira"])
def jira_update_issue(ctx: ToolContext, issue_key: str, fields: dict) -> dict:
    """Updates fields of an existing issue. Read jira_get_edit_fields first.
    Provided values replace the corresponding field content; omit unchanged fields.
    Use jira_set_status for status changes and jira_assign for assignment.

    issue_key: issue key
    fields: fields in Jira API format, e.g. {"summary":"New summary"} or {"priority":{"name":"High"}}"""
    if not isinstance(fields, dict) or not fields or set(fields) & {"project", "issuetype", "status", "assignee"}:
        raise InputValidationError("Fields are missing or include project, issue type, status or assignee. Use the specific tools.")
    editable = ctx.jira.edit_fields(issue_key)
    unknown = set(fields) - set(editable)
    if unknown:
        raise InputValidationError(f"Fields that cannot be edited: {', '.join(sorted(unknown))}")
    if "summary" in fields:
        JiraClient.check_text(fields["summary"], "Summary", 255)
    if "labels" in fields:
        _labels(fields["labels"])
    ctx.jira.update_fields(issue_key, **fields)
    return {"status": "OK", "key": ctx.jira.check_key(issue_key)}


@tool(write=True, needs=["jira"])
def jira_set_status(ctx: ToolContext, issue_key: str, status: str, comment: str = "",
                    fields: dict | None = None) -> dict:
    """Changes issue status using an available transition; read jira_list_transitions first.

    issue_key: issue key
    status: name/ID of an available transition or its target status
    comment: optional accompanying comment
    fields: additional transition fields from jira_list_transitions, e.g. resolution"""
    ctx.jira.transition(issue_key, status, comment, fields)
    return {"status": "OK"}


@tool(write=True, needs=["jira"])
def jira_set_priority(ctx: ToolContext, issue_key: str, priority: str) -> dict:
    """Sets issue priority. Query valid names with jira_list_priorities first.

    issue_key: issue key
    priority: actual priority name"""
    ctx.jira.set_priority(issue_key, JiraClient.check_text(priority, "Priority", 255))
    return {"status": "OK"}


@tool(write=True, needs=["jira"])
def jira_link_issues(ctx: ToolContext, from_key: str, to_key: str, link_type: str) -> dict:
    """Links two issues. Read jira_list_link_types first and explicitly describe the direction:
    from_key is outwardIssue and to_key is inwardIssue, e.g. from_key blocks to_key for Blocks.

    from_key: source issue (outwardIssue)
    to_key: target issue (inwardIssue)
    link_type: actual link type name"""
    if JiraClient.check_key(from_key) == JiraClient.check_key(to_key):
        raise InputValidationError("An issue cannot be linked to itself.")
    ctx.jira.link(from_key, to_key, JiraClient.check_text(link_type, "Link type", 255))
    return {"status": "OK"}


@tool(write=True, needs=["jira"])
def jira_add_worklog(ctx: ToolContext, issue_key: str, time_spent: str, comment: str = "") -> dict:
    """Logs work on an issue. Execute only after explicit approval.

    issue_key: issue key
    time_spent: Jira duration, e.g. 1h 30m or 2d
    comment: description of the work performed"""
    ctx.jira.add_worklog(issue_key, time_spent, comment)
    return {"status": "OK"}
