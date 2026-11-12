"""Beispiel für ein eigenes Tool – Vorlage zum Kopieren.

So bauen Sie ein eigenes Tool:
1. Datei in jira_agent/tools/ anlegen (z. B. mein_tool.py). Sie wird automatisch geladen.
2. Funktion mit @tool dekorieren. Der Docstring ist die Beschreibung für das Modell,
   Zeilen "name: Text" beschreiben die Parameter, die Typen kommen aus den Type-Hints.
3. Erstes Argument ist immer ctx (ToolContext): ctx.jira, ctx.sql, ctx.files, ctx.selected_tables.
   ctx.jira hat fertige Helfer: search, issue, create_issue, transitions, transition, assign, comment,
   comments, update_fields, set_priority, add_label, link, add_worklog, find_users, projects, fields.
4. needs=["jira"] blendet das Tool aus, solange kein Jira-Token gesetzt ist.
5. write=True für alles, was etwas verändert: Der Agent muss dann vorher "ja <CODE>" einholen.
6. Ein dict zurückgeben. Fehler einfach als Exception werfen – der Agent bekommt sie als Text.
7. Test schreiben: siehe tests/test_example_custom_tool.py (läuft ohne echtes Jira).
"""
from __future__ import annotations

import re

from jira_agent.tools import ToolContext, tool

_LABEL_RE = re.compile(r"[A-Za-z0-9_\-.]{1,64}")


@tool(write=True, needs=["jira"])
def jira_add_label(ctx: ToolContext, issue_key: str, label: str) -> dict:
    """Setzt ein Label an einem Jira-Ticket, z. B. 'auto-routed'.

    issue_key: Ticket-Key, z. B. ABC-123
    label: Label ohne Leerzeichen (Buchstaben, Ziffern, _ - .)
    """
    if not _LABEL_RE.fullmatch(label or ""):
        raise ValueError("Labels dürfen nur Buchstaben, Ziffern, _ - . enthalten (ohne Leerzeichen).")
    ctx.jira.add_label(issue_key, label)
    return {"status": "OK"}
