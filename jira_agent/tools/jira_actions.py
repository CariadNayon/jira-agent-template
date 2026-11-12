"""Wiederverwendbare Jira-Aktionen. Jede Änderung läuft durch dieselbe Bestätigungslogik.

Projektspezifische Abläufe gehören in skills/, zusätzliche Fähigkeiten in eigene Tool-Dateien.
Keine projektspezifischen Keys, Nutzer, Tickettypen oder Prioritäten hier fest einbauen.
"""
from __future__ import annotations

import re

from jira_agent.jira_client import JiraClient
from jira_agent.tools import ToolContext, tool


def _labels(labels: list[str]) -> list[str]:
    if any(not isinstance(x, str) or not re.fullmatch(r"[A-Za-z0-9_.-]{1,64}", x) for x in labels):
        raise ValueError("Labels: 1–64 Zeichen, nur Buchstaben, Ziffern, _ - .")
    return labels


@tool(write=True, needs=["jira"])
def jira_create_issue(ctx: ToolContext, project: str, summary: str, issue_type: str,
                      description: str = "", assignee: str = "", priority: str = "",
                      components: list[str] | None = None, labels: list[str] | None = None,
                      extra_fields: dict | None = None) -> dict:
    """Erstellt ein Jira-Ticket nach Nutzerbestätigung. Zuerst Projekt, Tickettypen und Pflichtfelder
    mit den Metadaten-Tools prüfen. Fehlende Angaben erfragen; keine Pflichtwerte erfinden.

    project: bestätigter Projekt-Key
    summary: Titel, maximal 255 Zeichen
    issue_type: tatsächlicher Tickettyp-Name aus jira_list_issue_types
    description: Beschreibung
    assignee: Jira-Kennung oder @me für den mit Jira verbundenen Benutzer; leer = Projektstandard
    priority: tatsächlicher Prioritätsname; leer = Projektstandard
    components: Komponentennamen aus den Create-Metadaten
    labels: Labels ohne Leerzeichen
    extra_fields: zusätzliche Jira-Felder im API-Format aus den Metadaten, z. B. customfield_10010 oder parent
    """
    fields = dict(extra_fields or {})
    if set(fields) & {"project", "summary", "issuetype", "description", "assignee", "priority", "components", "labels"}:
        raise ValueError("Standardfelder über die benannten Parameter angeben, nicht über extra_fields.")
    if any(not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*", k) for k in fields):
        raise ValueError("Ungültige Feld-ID.")
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
    """Ändert Felder eines bestehenden Tickets. Zuerst jira_get_edit_fields lesen.
    Die übergebenen Werte ersetzen den jeweiligen Feldinhalt; unveränderte Felder weglassen.
    Für Statuswechsel jira_set_status, für Zuweisung jira_assign verwenden.

    issue_key: Ticket-Key
    fields: Felder im Jira-API-Format, z. B. {"summary":"Neuer Titel"} oder {"priority":{"name":"High"}}
    """
    if not fields or set(fields) & {"project", "issuetype", "status", "assignee"}:
        raise ValueError("Felder fehlen oder enthalten Projekt, Tickettyp, Status oder Bearbeiter. Spezifische Tools verwenden.")
    editable = ctx.jira.edit_fields(issue_key)
    unknown = set(fields) - set(editable)
    if unknown:
        raise ValueError(f"Nicht bearbeitbare Felder: {', '.join(sorted(unknown))}")
    if "summary" in fields:
        JiraClient.check_text(fields["summary"], "Titel", 255)
    if "labels" in fields:
        _labels(fields["labels"])
    ctx.jira.update_fields(issue_key, **fields)
    return {"status": "OK", "key": ctx.jira.check_key(issue_key)}


@tool(write=True, needs=["jira"])
def jira_set_status(ctx: ToolContext, issue_key: str, status: str, comment: str = "",
                    fields: dict | None = None) -> dict:
    """Ändert den Ticketstatus über einen verfügbaren Übergang; vorher jira_list_transitions lesen.

    issue_key: Ticket-Key
    status: Name/ID eines verfügbaren Übergangs oder dessen Zielstatus
    comment: optionaler begleitender Kommentar
    fields: zusätzliche Felder des Übergangs aus jira_list_transitions, z. B. resolution
    """
    ctx.jira.transition(issue_key, status, comment, fields)
    return {"status": "OK"}


@tool(write=True, needs=["jira"])
def jira_set_priority(ctx: ToolContext, issue_key: str, priority: str) -> dict:
    """Setzt die Priorität. Vorher gültige Namen mit jira_list_priorities abfragen.

    issue_key: Ticket-Key
    priority: tatsächlicher Prioritätsname
    """
    ctx.jira.set_priority(issue_key, JiraClient.check_text(priority, "Priorität", 255))
    return {"status": "OK"}


@tool(write=True, needs=["jira"])
def jira_link_issues(ctx: ToolContext, from_key: str, to_key: str, link_type: str) -> dict:
    """Verknüpft zwei Tickets. Vorher jira_list_link_types lesen und Richtung ausdrücklich nennen:
    from_key ist outwardIssue, to_key inwardIssue, z. B. from_key blocks to_key bei Blocks.

    from_key: Ausgangsticket (outwardIssue)
    to_key: Zielticket (inwardIssue)
    link_type: tatsächlicher Name der Verknüpfungsart
    """
    if JiraClient.check_key(from_key) == JiraClient.check_key(to_key):
        raise ValueError("Ein Ticket kann nicht mit sich selbst verknüpft werden.")
    ctx.jira.link(from_key, to_key, JiraClient.check_text(link_type, "Verknüpfungsart", 255))
    return {"status": "OK"}


@tool(write=True, needs=["jira"])
def jira_add_worklog(ctx: ToolContext, issue_key: str, time_spent: str, comment: str = "") -> dict:
    """Bucht Arbeitszeit auf ein Ticket. Erst nach ausdrücklicher Bestätigung ausführen.

    issue_key: Ticket-Key
    time_spent: Jira-Dauer, z. B. 1h 30m oder 2d
    comment: Beschreibung der geleisteten Arbeit
    """
    ctx.jira.add_worklog(issue_key, time_spent, comment)
    return {"status": "OK"}
