# Jira Agent (Databricks App)

Persönlicher Jira- und Daten-Assistent als fertige Databricks App, gebaut mit OpenAI Agents SDK, MLflow `AgentServer` und Azure OpenAI.

**Was der Agent kann**
- **Jira** (mit dem persönlichen Token des Nutzers): Tickets suchen, Details lesen, Nutzer finden, Bearbeiter setzen, kommentieren, Labels setzen. Jede Änderung braucht die Bestätigung „ja <CODE>“.
- **Daten** (mit den Rechten des Nutzers): freigegebene Unity-Catalog-Tabellen beschreiben und per `SELECT` über das SQL Warehouse abfragen.
- **Ausgaben**: Diagramme (Balken, Linie, Torte, Streuung) sowie CSV- und Excel-Exporte.
- **Ohne Code anpassbar** über das Zahnrad in der App: Name, Regeln in natürlicher Sprache, Modell, freigegebene Tabellen. Die Anleitung steht in der App unter `/jira/guide`.

## Mit KI weiterentwickeln (empfohlen)

Repo in VS Code öffnen und Copilot oder Claude in normaler Sprache sagen, was du willst:

| Du sagst … | Die KI … |
|---|---|
| „Richte das Projekt ein.“ | meldet an, legt `.env` an |
| „Baue ein Tool, das den Status eines Tickets ändert.“ | schreibt Tool und Test, führt die Tests aus |
| „Starte die App lokal.“ | startet unter http://localhost:8000 |
| „Deploye die App.“ | prüft, lädt hoch, startet neu und nennt die URL |

Die Regeln für die KI stehen in [AGENTS.md](AGENTS.md), die Abläufe in [.claude/skills/](.claude/skills/).

## Wo was liegt

| Hier änderst du | |
|---|---|
| [jira_agent/config.yaml](jira_agent/config.yaml) | Jira-URL, Azure-Modell, Limits und Standardregeln |
| [databricks.yml](databricks.yml) → `variables` | **einzige** Stelle für App-Name, Secret (Azure-Key) und Warehouse |
| [jira_agent/tools/](jira_agent/tools/) | Tools; neue Datei = neues Tool. Vorlage: `example_custom_tool.py` |
| [tests/](tests/) | Tests; Vorlage für eigene Tools: `test_example_custom_tool.py` |

Alles andere ist Unterbau (Übersicht in [AGENTS.md](AGENTS.md)).

## Befehle

Voraussetzungen: [uv](https://docs.astral.sh/uv/getting-started/installation/) ≥ 0.9.17, [Databricks CLI](https://docs.databricks.com/aws/en/dev-tools/cli/install), Node.js 20+.

| Aufgabe | Befehl |
|---|---|
| Einrichten (einmalig) | `uv run quickstart --profile <profil> --skip-lakebase` |
| Tests (ohne Jira oder Databricks) | `uv run pytest tests -q` |
| Lokal starten | `uv run start-app`, danach http://localhost:8000 |
| Deploy prüfen | `uv run deploy --check` |
| Deployen | `uv run deploy` |
| Bestehende App übernehmen | `uv run deploy --bind` |
| Logs | `databricks apps logs <app_name> --profile <profil>` |

`uv run deploy` prüft das Bundle ([databricks.yml](databricks.yml)), lädt den Code hoch und startet die App neu. Dabei werden diese Ressourcen eingerichtet:
- `experiment`
- `secret`, wird zur Umgebungsvariable `AZURE_OPENAI_KEY`
- `sql-warehouse`, wird zur Umgebungsvariable `WAREHOUSE_ID`

Außerdem setzt es die User-Scopes `sql:restricted-query`, `catalog.*:read` und `workspace.workspace`. Die Werte kommen aus `variables` in `databricks.yml` und lassen sich einmalig überschreiben: `uv run deploy --var app_name=agent-test`. Ohne Skript geht auch `databricks bundle deploy` und danach `databricks bundle run agent_openai_agents_sdk`. Ist bei einer im UI angelegten App keine Ressource gesetzt, nutzt die App die Standardwerte aus `databricks.yml`. Für CI gibt es die GitHub Action [.github/workflows/deploy.yml](.github/workflows/deploy.yml), sie führt `uv run deploy --target prod` aus.

## Sicherheit und Betrieb

- **Bestätigung:** Schreib-Tools (`write=True`) laufen nur, wenn der Nutzer einen Code bestätigt hat, der genau an diese Aktion gebunden ist.
- **Genau 1 Worker:** Keys, Bestätigungscodes und erzeugte Dateien liegen nur im Arbeitsspeicher. `start-server` verweigert `--workers` > 1. Keys verfallen spätestens `session.credentials_ttl_hours` nach Beginn der Sitzung.
- **SQL:** Erlaubt ist nur genau ein `SELECT` auf freigegebenen Tabellen und mit eingebauten Funktionen. `ai_query`, `http_request`, `secret`, `reflect`, UC-Funktionen usw. sind gesperrt ([data.py](jira_agent/data.py)).
- **Bilder in der Chat-UI** werden per Content-Security-Policy nur von der App selbst geladen. So können eingeschleuste Markdown-Bilder keine Daten an fremde Server senden.
- **Datenschutz:** MLflow-Traces enthalten Chat-Inhalte inklusive Ticket-Texten und Abfrageergebnissen (keine Keys). Den Zugriff auf das MLflow-Experiment deshalb restriktiv vergeben.

## API

Die App bietet die [OpenAI Responses API](https://platform.openai.com/docs/api-reference/responses) über MLflows `ResponsesAgent`. Aufrufe brauchen ein Databricks-OAuth-Token (`databricks auth token`), PATs funktionieren nicht. Details: [Query an agent](https://docs.databricks.com/aws/en/generative-ai/agent-framework/query-agent).

```python
from databricks.sdk import WorkspaceClient
from databricks_openai import DatabricksOpenAI

client = DatabricksOpenAI(workspace_client=WorkspaceClient())
response = client.responses.create(model="apps/<app-name>", input=[{"role": "user", "content": "Meine offenen Tickets?"}])
```

Lokal: `curl -X POST http://localhost:8000/invocations -H "Content-Type: application/json" -d '{"input":[{"role":"user","content":"hi"}]}'`

## Probleme

| Problem | Lösung |
|---|---|
| `An app with the same name already exists` | `uv run deploy --bind` (übernimmt die App) oder `app_name` in `databricks.yml` ändern |
| App läuft mit altem Code | `uv run deploy` startet immer neu; danach die Seite mit Strg+Shift+R neu laden |
| `Provider produced inconsistent result after apply` | `databricks apps get <name> -o json` ansehen und Felder wie `budget_policy_id` in `databricks.yml` übernehmen |
| Stream meldet 200, aber Fehler im Inhalt | normal: Fehler beim Streaming kommen im Stream selbst |
| HTTP 302 beim API-Aufruf | OAuth-Token statt PAT verwenden |
| Warnung `exclude-newer = "7 days"` | `uv self update` |
