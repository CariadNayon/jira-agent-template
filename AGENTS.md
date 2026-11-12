# Jira-Agent – Anleitung für KI-Assistenten

Dieses Repo ist eine **fertige Databricks App**: ein persönlicher Jira- und Daten-Assistent (OpenAI Agents SDK, MLflow AgentServer, Azure OpenAI). Die Nutzer dieses Repos sind meist **keine Entwickler**. Daher:

- Antworte auf **Deutsch**, kurz, in einfachen Worten. Fachbegriffe kurz erklären.
- Arbeite die Aufgabe **selbst** ab (Dateien anlegen, Tests ausführen, deployen) statt Anleitungen zu geben.
- Frage nur nach, wenn eine Entscheidung wirklich beim Nutzer liegt (z. B. bestehende App überschreiben?).
- Baue auf dem Vorhandenen auf. Keine neuen Frameworks, MCP-Server, Datenbanken oder Pakete ohne Rückfrage.

## Aufgabe → Skill

**Vor jeder Aufgabe die passende Skill-Datei lesen** und ihr folgen:

| Der Nutzer will … | Skill |
|---|---|
| Umgebung einrichten, erster Start, Anmeldefehler | `.claude/skills/einrichten/SKILL.md` |
| dass der Agent etwas Neues **kann** (Jira-Aktion, Abfrage, Export …) | `.claude/skills/neues-tool/SKILL.md` |
| lokal starten / testen | `.claude/skills/run-locally/SKILL.md` |
| deployen, App aktualisieren, Logs | `.claude/skills/deploy/SKILL.md` |

Regeln, Name, Modell und Tabellen ändern Nutzer **ohne Code** über das Zahnrad in der App – darauf hinweisen, wenn das reicht.

## Wo was liegt

**Hier wird erweitert:**

| Datei / Ordner | Inhalt |
|---|---|
| `jira_agent/config.yaml` | Jira-URL, Azure-Endpoint/Deployment, Limits, Standardregeln |
| `databricks.yml` → `variables` | **Einzige** Stelle für App-Name, Secret (Azure-Key) und Warehouse – gilt für Deploy und als Laufzeit-Fallback |
| `jira_agent/tools/` | Tools des Agenten – neue Datei = neues Tool (`@tool`). Vorlage: `example_custom_tool.py` |
| `jira_agent/jira_client.py` | Jira-Helfer (`ctx.jira.transition(...)`, `create_issue`, …) |
| `tests/` | Tests; Vorlage für eigene Tools: `test_example_custom_tool.py` |

**Unterbau (nur bei Bedarf ändern):**

| Datei | Inhalt |
|---|---|
| `jira_agent/runtime.py` | baut pro Anfrage den Agenten (System-Prompt `INSTRUCTIONS`, Modell, Tools) |
| `jira_agent/adapter.py` | Tools → Agents SDK, erzwingt Bestätigung "ja <CODE>" |
| `jira_agent/data.py` | lesender SQL-Zugriff + SQL-Prüfung |
| `jira_agent/llm.py` | Modell-Provider (Azure Team-Key / eigener Key) |
| `jira_agent/web.py`, `static/` | Zahnrad-UI, Anleitung (`/jira/guide`), Downloads |
| `jira_agent/state.py` | Sitzungsdaten im Speicher (Keys, Dateien) |
| `jira_agent/testing.py` | FakeJira, FakeSql, FakeFiles, `run_tool` für Tests |
| `agent_server/` | Server aus der Databricks-Vorlage |
| `databricks.yml` (Rest) | Bundle: Ressourcen, Scopes, Umgebungsvariablen der App |
| `scripts/deploy.py` | `uv run deploy` |

## Sicherheitsregeln (immer einhalten)

1. Tools, die etwas **ändern**, bekommen `write=True` – nie umgehen oder abschwächen.
2. SQL nur über `ctx.sql` und `check_readonly_sql` (ein SELECT, nur freigegebene Tabellen, nur eingebaute Funktionen).
3. Keine Tokens, Keys oder Passwörter in Code, Tool-Ergebnissen, Logs, Traces oder `settings.json`. Jira-Tokens liegen nur im Speicher.
4. Eingaben prüfen (`JiraClient.check_key`, `check_user`, Regex).
5. Die App läuft mit **genau einem Worker** (Sitzungsdaten im Speicher).
6. Daten werden mit den Rechten des **angemeldeten Nutzers** gelesen, nie mit denen der App.

## Befehle

| Aufgabe | Befehl |
|---|---|
| Tests | `uv run pytest tests -q` |
| Lokal starten | `uv run start-app` |
| Deploy prüfen | `uv run deploy --check` |
| Deployen | `uv run deploy` |
| Logs | `databricks apps logs <app_name> --profile <profil>` |

Alle `databricks`-Befehle mit dem Profil aus `.env` (`DATABRICKS_CONFIG_PROFILE`) ausführen. Nach jeder Code-Änderung: Tests ausführen; erst bei Grün deployen.
