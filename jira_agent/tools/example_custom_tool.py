"""Beispiel für ein eigenes Tool – Vorlage zum Kopieren.

So bauen Sie ein eigenes Tool:
1. Datei in jira_agent/tools/ anlegen (z. B. mein_tool.py). Sie wird automatisch geladen.
2. Funktion mit @tool dekorieren: Beschreibung, Parameter (JSON-Schema), Pflichtfelder.
3. Erstes Argument ist immer ctx (ToolContext): ctx.jira, ctx.sql, ctx.files, ctx.selected_tables.
4. needs=["jira"] blendet das Tool aus, solange kein Jira-Token gesetzt ist.
5. write=True für alles, was etwas verändert: Der Agent muss dann vorher "ja <CODE>" einholen.
6. Ein dict zurückgeben. Fehler einfach als Exception werfen – der Agent bekommt sie als Text.
"""
from __future__ import annotations

import re

from jira_agent.jira_client import JiraClient
from jira_agent.tools import ToolContext, tool

_LABEL_RE = re.compile(r"[A-Za-z0-9_\-.]{1,64}")


@tool("Setzt ein Label an einem Jira-Ticket, z. B. 'auto-routed'.",
      {"issue_key": {"type": "string"}, "label": {"type": "string"}},
      ["issue_key", "label"], write=True, needs=["jira"])
def jira_add_label(ctx: ToolContext, issue_key: str, label: str) -> dict:
    key = JiraClient.check_key(issue_key)
    if not _LABEL_RE.fullmatch(label or ""):
        raise ValueError("Labels dürfen nur Buchstaben, Ziffern, _ - . enthalten (ohne Leerzeichen).")
    r = ctx.jira.request("PUT", f"/issue/{key}", json={"update": {"labels": [{"add": label}]}})
    return {"status": "OK"} if r.status_code == 204 else {"error": r.status_code, "details": r.text[:300]}
