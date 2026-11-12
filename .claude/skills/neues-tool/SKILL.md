---
name: neues-tool
description: "Neues Tool für den Jira-Agenten bauen (Jira-Aktion, Datenabfrage, Datei-Export …). Verwenden bei: 'baue ein Tool', 'der Agent soll … können', 'neue Funktion', 'Jira-Aktion hinzufügen'."
---

# Neues Tool bauen

Ein Tool ist eine Python-Funktion mit `@tool` in einer Datei unter `jira_agent/tools/`. Neue Dateien werden automatisch geladen – nichts anderes registrieren.

## Schritte

1. **Klären** (falls unklar, kurz nachfragen): Was soll das Tool tun? Ändert es etwas (→ `write=True`)? Braucht es Jira, freigegebene Tabellen oder Dateien (→ `needs`)?
2. **Datei anlegen**: `jira_agent/tools/<thema>.py` (Kleinbuchstaben, Unterstriche). Vorlage: `jira_agent/tools/example_custom_tool.py`.
3. **Tool schreiben** – nach diesem Muster:

```python
from __future__ import annotations

from jira_agent.tools import ToolContext, tool


@tool(write=True, needs=["jira"])
def jira_set_status(ctx: ToolContext, issue_key: str, status: str, comment: str = "") -> dict:
    """Ändert den Status eines Tickets (z. B. 'In Arbeit', 'Erledigt').

    issue_key: Ticket-Key, z. B. ABC-123
    status: Name des Statuswechsels oder Zielstatus
    comment: optionaler Kommentar zum Statuswechsel
    """
    ctx.jira.transition(issue_key, status, comment=comment)
    return {"status": "OK"}
```

   - Erster Absatz des Docstrings = Beschreibung für das Modell (Deutsch, konkret, mit Beispiel).
   - `name: Text`-Zeilen = Parameterbeschreibungen. Typen aus Type-Hints: `str`, `int`, `float`, `bool`, `list[str]`, `Literal["a", "b"]`. Ohne Standardwert = Pflicht.
   - Rückgabe: kleines `dict`. Lesende visuelle Tools können `VisualResult` aus `jira_agent/visual_output.py` liefern; siehe `jira_agent/tools/pdf_tools.py` und `docs/EXTENDING.md`. SDK-Läufe verwenden dafür `make_run_config()` aus `jira_agent/model_input.py`.
   - Fehler als Exception werfen (`ValueError("verständlicher Text")`).
   - Bilder/Downloads: `url = ctx.files.put(name, mime, bytes)` und `{"markdown": f"![Titel]({url})"}` zurückgeben (siehe `output_tools.py`).

4. **Jira nur über die Helfer** in `ctx.jira` (keine eigenen HTTP-Aufrufe, wenn ein Helfer passt):
   `search`, `issue`, `create_issue`, `transitions`, `transition`, `assign`, `comment`, `comments`, `update_fields`, `set_priority`, `add_label`, `link`, `add_worklog`, `find_users`, `projects`, `fields`. Fehlt etwas: Helfer in `jira_agent/jira_client.py` ergänzen (über `self._call(...)`), dann `FakeJira` in `jira_agent/testing.py` erweitern.
5. **Daten nur über** `ctx.sql.query(check_readonly_sql(sql, ctx.selected_tables))` bzw. `ctx.sql.describe(...)` – nie eigene Verbindungen.
6. **Test schreiben**: `tests/test_<thema>.py`, Vorlage `tests/test_example_custom_tool.py`:

```python
from jira_agent.testing import FakeJira, run_tool

def test_status_wird_gesetzt():
    jira = FakeJira(issues={"ABC-1": {}})
    assert run_tool("jira_set_status", jira=jira, issue_key="ABC-1", status="Erledigt") == {"status": "OK"}
    assert jira.issues["ABC-1"]["status"] == "Erledigt"
```

   Für Daten: `FakeSql(columns, rows)`, für Dateien: `FakeFiles()` (beide in `jira_agent/testing.py`).
7. **Prüfen**: `uv run pytest tests -q` – alles muss grün sein.
8. **Nutzer informieren**: Was das Tool kann, eine Beispiel-Frage für den Chat, und dass es nach dem Deploy (Skill **deploy**) in der App verfügbar ist.

## Regeln (nicht verhandelbar)

- Alles, was in Jira oder anderswo etwas ändert: `write=True`. Die Bestätigung "ja <CODE>" ist dann automatisch erzwungen.
- Keine Tokens, Keys oder Passwörter in Code, Rückgaben oder Logs.
- Eingaben prüfen (z. B. `JiraClient.check_key`, Regex für freie Texte, die in URLs landen).
- Keine neuen Pakete ohne Rückfrage; wenn nötig: `uv add <paket>`.
