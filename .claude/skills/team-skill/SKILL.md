---
name: team-skill
description: "Skill für den Jira-Agenten im Repo anlegen oder übernehmen (für alle Nutzer, Ordner skills/). Verwenden bei: 'füge diesen Skill ein', angehängte .md-Datei aus 'Für Team vorschlagen', 'neuer Skill', 'Skill fürs Team', '/befehl für alle'."
---

# Team-Skill anlegen oder übernehmen

Agent-Skills sind Markdown-Dateien in `skills/` (Repo-Wurzel). Sie gelten für alle Nutzer der App und werden im Chat mit `/name` aufgerufen. (Nicht verwechseln mit `.claude/skills/` – das sind Anleitungen für dich, die Entwickler-KI.)

## Format

```markdown
---
name: wochenreport
beschreibung: Wochenbericht meiner Tickets mit Excel-Export
---
1. Schritt …
2. Schritt …
```

- `name`: 2–40 Zeichen, nur Kleinbuchstaben, Ziffern, Bindestriche; Dateiname = `<name>.md`.
- `beschreibung`: ein Satz, max. 200 Zeichen (erscheint in der `/`-Auswahl).
- Anleitung: nummerierte Schritte an den Agenten, max. 8000 Zeichen. Konkrete Tool-Namen und JQL nennen.

## Ablauf

1. **Quelle**:
   - Angehängte `.md`-Datei (aus „Für Team vorschlagen“ im Zahnrad) → Inhalt übernehmen.
   - Beschreibung in Worten → Skill daraus schreiben (Beispiele: `skills/triage.md`, `skills/wochenreport.md`).
2. **Prüfen**:
   - Name frei? (`skills/<name>.md` existiert nicht – sonst Nutzer fragen: ersetzen oder neuer Name?)
   - Nur Tools verwenden, die es gibt (Funktionen mit `@tool` in `jira_agent/tools/*.py`).
     Fehlt ein Tool, das der Skill braucht → zuerst Skill **neues-tool** befolgen.
   - Schreibende Schritte (zuweisen, kommentieren …) nur „vorschlagen und nach Bestätigung ausführen“.
3. **Ablegen**: `skills/<name>.md`.
4. **Testen**: `uv run pytest tests -q` (prüft u. a. Format und Tool-Namen aller Dateien in `skills/`).
5. **Deployen**: Skill **deploy**. Danach erscheint `/name` bei allen Nutzern.
6. **Nutzer informieren**: Aufruf (`/name …`) und ein Beispiel. Gibt es den Namen schon als persönlichen Skill: Hinweis, dass der Team-Skill jetzt Vorrang hat und der persönliche im Zahnrad gelöscht werden kann.
