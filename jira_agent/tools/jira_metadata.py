"""Lesende Erkundung: Projekte und erlaubte Eingaben aus Jira statt aus Modellwissen."""
from __future__ import annotations

from jira_agent.tools import ToolContext, tool


def field_summary(field_id: str, meta: dict, value_query: str = "", value_offset: int = 0) -> dict:
    values = meta.get("allowedValues", [])
    if value_query:
        values = [x for x in values if any(value_query.casefold() in str(x.get(k, "")).casefold()
                                         for k in ("id", "name", "value", "key", "displayName"))]
    offset = max(0, value_offset)
    return {"id": field_id, "name": meta.get("name"), "required": meta.get("required", False),
            "schema": meta.get("schema", {}), "operations": meta.get("operations", []),
            "has_default": meta.get("hasDefaultValue", False),
            "allowed_values": [{k: v for k, v in x.items() if k in
                                ("id", "name", "value", "key", "displayName")} for x in values[offset:offset + 30]],
            "allowed_values_total": len(values), "allowed_values_offset": offset,
            "allowed_values_truncated": len(values) > offset + 30,
            "autocomplete_url": meta.get("autoCompleteUrl")}


def summarize_fields(fields: list[tuple[str, dict]], field_id: str, value_query: str, value_offset: int) -> dict:
    if field_id:
        match = next((meta for key, meta in fields if key == field_id), None)
        if match is None:
            raise ValueError(f"Field {field_id} is unavailable here.")
        return {"fields": [field_summary(field_id, match, value_query, value_offset)]}
    return {"fields": [{"id": key, "name": meta.get("name"), "required": meta.get("required", False),
                        "schema": meta.get("schema", {}), "has_default": meta.get("hasDefaultValue", False),
                        "allowed_values_total": len(meta.get("allowedValues", []))}
                       for key, meta in fields],
            "hint": "Call again with field_id for allowed values; search with value_query or paginate with value_offset."}


@tool(needs=["jira"])
def jira_get_myself(ctx: ToolContext) -> dict:
    """Identifies the connected Jira user for 'I', 'me' and 'my issues'."""
    user = ctx.jira.myself()
    return {k: user.get(k) for k in ("name", "key", "displayName", "active")}


@tool(needs=["jira"])
def jira_list_projects(ctx: ToolContext) -> dict:
    """Lists projects visible to the Jira user and their project keys."""
    return {"projects": ctx.jira.projects()}


@tool(needs=["jira"])
def jira_list_issue_types(ctx: ToolContext, project: str) -> dict:
    """Lists issue types available for creation in a project, including IDs for required-field queries.

    project: project key from jira_list_projects, e.g. ABC"""
    return {"issue_types": [{k: t.get(k) for k in ("id", "name", "subtask")}
                            for t in ctx.jira.project_issue_types(project)]}


@tool(needs=["jira"])
def jira_get_create_fields(ctx: ToolContext, project: str, issue_type_id: str, field_id: str = "",
                           value_query: str = "", value_offset: int = 0) -> dict:
    """Returns required fields, field types and allowed values BEFORE creating an issue.
    First obtain the issue type ID with jira_list_issue_types. Ask for missing required information.

    project: project key
    issue_type_id: numeric issue type ID from jira_list_issue_types
    field_id: optional field ID for allowed values; empty returns the field overview
    value_query: optional search text within allowed field values
    value_offset: start position in allowed values; at most 30 per call"""
    fields = [(f.get("fieldId") or f.get("key") or "", f)
              for f in ctx.jira.create_fields(project, issue_type_id)]
    return summarize_fields(fields, field_id, value_query, value_offset)


@tool(needs=["jira"])
def jira_get_edit_fields(ctx: ToolContext, issue_key: str, field_id: str = "",
                         value_query: str = "", value_offset: int = 0) -> dict:
    """Lists editable fields and allowed values for an existing issue.

    issue_key: issue key, e.g. ABC-123
    field_id: specific field ID for values; empty returns the field overview
    value_query: optional search text within allowed values
    value_offset: start position in allowed values; at most 30 per call"""
    return summarize_fields(list(ctx.jira.edit_fields(issue_key).items()), field_id, value_query, value_offset)


@tool(needs=["jira"])
def jira_list_transitions(ctx: ToolContext, issue_key: str) -> dict:
    """Lists available status transitions. jira_set_status must use one of these transitions.

    issue_key: issue key, e.g. ABC-123"""
    transitions = ctx.jira.transitions(issue_key)
    for transition in transitions:
        transition["fields"] = [field_summary(key, meta) for key, meta in transition["fields"].items()]
    return {"transitions": transitions}


@tool(needs=["jira"])
def jira_list_priorities(ctx: ToolContext) -> dict:
    """Lists Jira priorities with actual names and IDs. Do not translate or guess them."""
    return {"priorities": [{k: p.get(k) for k in ("id", "name", "description")}
                           for p in ctx.jira.priorities()]}


@tool(needs=["jira"])
def jira_list_link_types(ctx: ToolContext) -> dict:
    """Lists issue link types with inward/outward direction, e.g. Blocks / blocks / is blocked by."""
    return {"link_types": ctx.jira.link_types()}


@tool(needs=["jira"])
def jira_get_comments(ctx: ToolContext, issue_key: str, max_results: int = 20) -> dict:
    """Reads comments on an issue.

    issue_key: issue key
    max_results: number of comments, 1 to 50"""
    return {"comments": ctx.jira.comments(issue_key, max(1, min(max_results, 50)))}
