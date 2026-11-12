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
            raise ValueError(f"Feld {field_id} ist hier nicht verfügbar.")
        return {"fields": [field_summary(field_id, match, value_query, value_offset)]}
    return {"fields": [{"id": key, "name": meta.get("name"), "required": meta.get("required", False),
                        "schema": meta.get("schema", {}), "has_default": meta.get("hasDefaultValue", False),
                        "allowed_values_total": len(meta.get("allowedValues", []))}
                       for key, meta in fields],
            "hint": "Für erlaubte Werte erneut mit field_id aufrufen; mit value_query suchen oder value_offset blättern."}


@tool(needs=["jira"])
def jira_get_myself(ctx: ToolContext) -> dict:
    """Ermittelt den mit Jira verbundenen Benutzer für 'ich', 'mir', 'meine Tickets'."""
    user = ctx.jira.myself()
    return {k: user.get(k) for k in ("name", "key", "displayName", "active")}


@tool(needs=["jira"])
def jira_list_projects(ctx: ToolContext) -> dict:
    """Listet die für den Jira-Benutzer sichtbaren Projekte mit ihren Projekt-Keys."""
    return {"projects": ctx.jira.projects()}


@tool(needs=["jira"])
def jira_list_issue_types(ctx: ToolContext, project: str) -> dict:
    """Liefert erstellbare Tickettypen eines Projekts, einschließlich IDs für Pflichtfeldabfragen.

    project: Projekt-Key aus jira_list_projects, z. B. WEST1
    """
    return {"issue_types": [{k: t.get(k) for k in ("id", "name", "subtask")}
                            for t in ctx.jira.project_issue_types(project)]}


@tool(needs=["jira"])
def jira_get_create_fields(ctx: ToolContext, project: str, issue_type_id: str, field_id: str = "",
                           value_query: str = "", value_offset: int = 0) -> dict:
    """Liefert Pflichtfelder, Feldtypen und erlaubte Werte VOR dem Erstellen eines Tickets.
    IDs und Tickettyp zuerst mit jira_list_issue_types ermitteln. Fehlende Pflichtangaben erfragen.

    project: Projekt-Key
    issue_type_id: numerische Tickettyp-ID aus jira_list_issue_types
    field_id: optional konkrete Feld-ID für erlaubte Werte; leer = Feldübersicht
    value_query: optionaler Suchtext in den erlaubten Werten des Felds
    value_offset: Startposition in erlaubten Werten; jeweils maximal 30
    """
    fields = [(f.get("fieldId") or f.get("key") or "", f)
              for f in ctx.jira.create_fields(project, issue_type_id)]
    return summarize_fields(fields, field_id, value_query, value_offset)


@tool(needs=["jira"])
def jira_get_edit_fields(ctx: ToolContext, issue_key: str, field_id: str = "",
                         value_query: str = "", value_offset: int = 0) -> dict:
    """Zeigt bearbeitbare Felder und deren zulässige Werte für ein bestehendes Ticket.

    issue_key: Ticket-Key, z. B. ABC-123
    field_id: konkrete Feld-ID für Werte; leer = Feldübersicht
    value_query: optionaler Suchtext in erlaubten Werten
    value_offset: Startposition in erlaubten Werten; jeweils maximal 30
    """
    return summarize_fields(list(ctx.jira.edit_fields(issue_key).items()), field_id, value_query, value_offset)


@tool(needs=["jira"])
def jira_list_transitions(ctx: ToolContext, issue_key: str) -> dict:
    """Zeigt mögliche Statuswechsel. Nur diese Übergänge darf jira_set_status verwenden.

    issue_key: Ticket-Key, z. B. ABC-123
    """
    transitions = ctx.jira.transitions(issue_key)
    for transition in transitions:
        transition["fields"] = [field_summary(key, meta) for key, meta in transition["fields"].items()]
    return {"transitions": transitions}


@tool(needs=["jira"])
def jira_list_priorities(ctx: ToolContext) -> dict:
    """Listet Jira-Prioritäten mit tatsächlichem Namen und ID (nicht übersetzen oder erraten)."""
    return {"priorities": [{k: p.get(k) for k in ("id", "name", "description")}
                           for p in ctx.jira.priorities()]}


@tool(needs=["jira"])
def jira_list_link_types(ctx: ToolContext) -> dict:
    """Listet Verknüpfungsarten mit inward/outward-Richtung, z. B. Blocks / blocks / is blocked by."""
    return {"link_types": ctx.jira.link_types()}


@tool(needs=["jira"])
def jira_get_comments(ctx: ToolContext, issue_key: str, max_results: int = 20) -> dict:
    """Liest Kommentare eines Tickets.

    issue_key: Ticket-Key
    max_results: Anzahl Kommentare, 1 bis 50
    """
    return {"comments": ctx.jira.comments(issue_key, max(1, min(max_results, 50)))}
