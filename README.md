# Jira Agent (Databricks App)

Persönlicher Jira- und Daten-Assistent als fertige Databricks App, gebaut mit OpenAI Agents SDK, MLflow `AgentServer` und Azure OpenAI.

Die laufende App-Version steht dezent oben links neben dem Agentennamen. Zentrale Quelle ist `project.version` in `pyproject.toml`; sie wird mit jedem Release erhöht und vom Backend an die Oberfläche übergeben.

**Was der Agent kann**
- **Jira** (mit dem persönlichen Token des Nutzers): Tickets suchen, erstellen und bearbeiten; Benutzer, Projekte, Tickettypen und Pflichtfelder ermitteln; Bearbeiter, Status und Priorität setzen; kommentieren, Labels setzen, Tickets verknüpfen und Arbeitszeit buchen. Jede Änderung braucht die Bestätigung „yes <CODE>“, per Button **Approve action** unter der Antwort oder durch Tippen; **Decline** lehnt ab. Optional schaltet der Knopf **Auto-approve** im Kopf die automatische Bestätigung für die nächsten 5 Aktionen in diesem Browser-Tab ein (standardmäßig aus, die App prüft den Code weiterhin serverseitig).
- **Daten** (mit den Rechten des Nutzers): freigegebene Unity-Catalog-Tabellen beschreiben und per `SELECT` über das SQL Warehouse abfragen.
- **Anhänge**: PNG/JPEG/WebP werden über eindeutige Dateireferenzen als echte Bild-Eingaben an das Modell übergeben. CSV, XLSX/XLSM und Text können gelesen werden. PDF-Text wird seitenweise gelesen; Scan-PDFs werden mit PDFium gerendert und an das Bildmodell übergeben. Tabellen lassen sich über alle eingelesenen Zeilen filtern, gruppieren, berechnen, als Diagramm darstellen und exportieren. Anhänge sind benutzer- und chatbezogen; Bilder benötigen ein bildfähiges Azure-Deployment.
- **Ausgaben**: Diagramme (Balken, Linie, Torte, Streuung) sowie CSV- und Excel-Exporte.
- **Ohne Code anpassbar** über das Zahnrad in der App: Name, Regeln in natürlicher Sprache, Modell, freigegebene Tabellen. Die Anleitung steht in der App unter `/jira/guide`.

## Mit KI weiterentwickeln (empfohlen)

Repo in VS Code öffnen und Copilot oder Claude in normaler Sprache sagen, was du willst:

| Du sagst … | Die KI … |
|---|---|
| „Richte das Projekt ein.“ | meldet an, legt `.env` an |
| „Ergänze ein Tool für unseren projektspezifischen Jira-Ablauf.“ | schreibt Tool und Test, führt die Tests aus |
| „Starte die App lokal.“ | startet unter http://localhost:8000 |
| „Deploye die App.“ | prüft, lädt hoch, startet neu und nennt die URL |

Die Regeln für die KI stehen in [AGENTS.md](AGENTS.md), die Abläufe in [.claude/skills/](.claude/skills/).

Die Umsetzung des robusteren Advanced-Unterbaus ist in [IMPLEMENTATION_PLAN.md](docs/IMPLEMENTATION_PLAN.md) beschrieben. Aktueller erster Meilenstein: [Stabilitätsprüfung](docs/STABILITY.md). Optionaler gemeinsamer Skill-Katalog in Unity Catalog (standardmäßig aus, einmalige Einrichtung): [REGISTRY.md](docs/REGISTRY.md).

## Wiederverwenden und erweitern

Jira ist der Basis-Anwendungsfall. Die Laufzeit, Tool-Registrierung, Bestätigungen und Skills können für eigene Agenten wiederverwendet werden. [Erweiterungsleitfaden](docs/EXTENDING.md): Architektur, Tool-Auswahl über `agent.enabled_tools`, neue Integrationen und Tests.

Beispiele im Chat:
- `/show-ticket ABC-123`, `/search-tickets my open tickets in ABC` und `/edit-ticket ABC-123 change the summary to …` nutzen vorbereitete Abläufe für Anzeigen, Suchen und Bearbeiten. Normale Chat-Anfragen nutzen dieselben Grundregeln.
- „Erstelle ein Testticket im Projekt ABC und weise es mir zu.“ Der Agent klärt Tickettyp und Pflichtfelder, zeigt eine Vorschau und wartet auf `yes CODE`.
- „Welche Statuswechsel sind für ABC-123 möglich?“
- „Ändere die Beschreibung von ABC-123 auf …“
- „Verknüpfe ABC-123 so, dass es ABC-456 blockiert.“
- `/file-analysis` führt durch Dokument- und Tabellenanalysen.
- `/issue-draft` führt durch einen wiederverwendbaren Erstellungsablauf.

Tool-Aufrufe sind standardmäßig eingeklappt; Name und Status bleiben sichtbar. Ein Klick öffnet Parameter und Ergebnis. Die gewöhnliche Ticket-Suche nutzt `jira_search_tickets` mit festen Filtern; `jira_search` bleibt für erweiterte JQL-Abfragen verfügbar.

Jira-Zugangsdaten ausschließlich im Feld **Jira verbinden** oder unter Zahnrad → Zugänge einfügen, niemals als Chatnachricht. Die tatsächlichen Projektberechtigungen gelten weiterhin. Die Integration unterstützt Jira Data Center; Jira Cloud benötigt Anpassungen.

Mit **Remember for my account** kann der Jira-Token optional verschlüsselt pro Databricks-Nutzer gespeichert werden. Nach erneuter Anmeldung wird er wiederhergestellt und gegen Jira geprüft. **Disconnect and forget saved token** entfernt die gespeicherte Kopie und die Sitzungsschlüssel. Einmalige Einrichtung des separaten App-Secrets und die genaue Ablage: [TOKEN_STORAGE.md](docs/TOKEN_STORAGE.md).

Ohne diese Einrichtung kann der **Passwortmanager des Browsers** (Edge/Chrome) den Token speichern und beim nächsten Mal ins Feld einfügen. Dafür sind die Token-Felder normale Anmeldeformulare. Die App selbst legt weiterhin nichts im Browser-Speicher ab.

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
| Stabilitätsfälle wiederholen (offline) | `uv run stability-check --repeat 2` |
| Jira-/Datei-Abnahme (offline) | `uv run agent-evaluate` |
| Optionale Modelltests anzeigen | `uv run agent-evaluate --list` |
| Lokal starten | `uv run start-app`, danach http://localhost:8000 |
| Deploy prüfen | `uv run deploy --check` |
| Deployen | `uv run deploy` |
| Bestehende App übernehmen | `uv run deploy --bind` |
| Logs | `databricks apps logs <app_name> --profile <profil>` |

`uv run deploy` prüft das Bundle ([databricks.yml](databricks.yml)), lädt den Code hoch und startet die App neu. Dabei werden diese Ressourcen eingerichtet:
- `experiment`
- `secret`, wird zur Umgebungsvariable `AZURE_OPENAI_KEY`
- `sql-warehouse`, wird zur Umgebungsvariable `WAREHOUSE_ID`

Außerdem setzt es die User-Scopes `sql`, `catalog.*:read` und `workspace.workspace`. Der Scope `sql` (früher `sql:restricted-query`) ist für das Veröffentlichen von Skills im Katalog nötig; Chat-Abfragen bleiben durch `check_readonly_sql` auf ein einzelnes SELECT beschränkt. Nach einer Änderung der Scopes müssen sich Nutzer neu anmelden und zustimmen. Die Werte kommen aus `variables` in `databricks.yml` und lassen sich einmalig überschreiben: `uv run deploy --var app_name=agent-test`. Ohne Skript geht auch `databricks bundle deploy` und danach `databricks bundle run agent_openai_agents_sdk`. Ist bei einer im UI angelegten App keine Ressource gesetzt, nutzt die App die Standardwerte aus `databricks.yml`.

Die GitHub Action [checks.yml](.github/workflows/checks.yml) prüft Änderungen auf `main` automatisch: Python 3.11/3.12, Offline-Abnahme und der vollständige Build des angepassten Chat-Frontends. Die manuell gestartete [Deploy-Action](.github/workflows/deploy.yml) führt diese Prüfungen vor `uv run deploy --target prod` aus. Reale Modell-, Anmelde- und Berechtigungstests sind separat beschrieben: [Abnahme](docs/ACCEPTANCE.md).

In dieser Installation wird nach einem Push nicht über die GitHub Deploy-Action, sondern über einen Databricks Git-Ordner bzw. Job deployt; der `push`-Trigger in `deploy.yml` bleibt deshalb ausgeschaltet. Ob ein Stand live ist, zeigt die Versionsnummer oben links in der App. Deshalb bei jeder Änderung `project.version` in `pyproject.toml` erhöhen. Auf diesem Weg laufen die Prüfungen aus `checks.yml` nicht vor dem Deploy: vorher lokal `uv run pytest tests -q` ausführen.

## Sicherheit und Betrieb

Gemeinsame Laufzeitoptimierungen und Auswertung langsamer Anfragen: [Performance](docs/PERFORMANCE.md). HTTP-Verbindungen werden wiederverwendet, der Modellkontext richtet sich nach den verfügbaren Fähigkeiten und jeder Lauf protokolliert getrennte Modell-, Tool- und Jira-Zeiten.

- **Bestätigung:** Schreib-Tools (`write=True`) benötigen einen einmaligen Code (10 Minuten gültig), gebunden an Sitzung, Gespräch und Argumente. Wiederholte Aufrufe derselben Bestätigung liefern einen Aktionsbeleg. Bei Verbindungsfehlern wird kein zweiter Agentenlauf automatisch gestartet. Belege liegen nur im Arbeitsspeicher; nach Neustarts ungeklärte Änderungen zuerst in Jira prüfen.
- **Genau 1 Worker:** Klartext-Keys, Bestätigungscodes und erzeugte Dateien liegen im Arbeitsspeicher. `start-server` verweigert `--workers` > 1. Die Sitzung verfällt nach `session.credentials_ttl_hours`; ein optional gemerkter Jira-Token kann anschließend nach Nutzeranmeldung aus der verschlüsselten Ablage wiederhergestellt werden. Azure-Nutzerkeys werden nicht gespeichert.
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
| Meldung `The AI model service is rate-limited (429)` | Azure drosselt Modellanfragen. Ab v0.4.0 werden Anfragen pro Deployment eingereiht und bekannte Wartezeiten gemeinsam beachtet. Der Agents SDK wiederholt nur den abgewiesenen Modellaufruf, höchstens zweimal und innerhalb eines kumulativen Queue-/Cooldown-Budgets von 60 Sekunden. Bereits ausgeführte Tools werden dabei nicht neu gestartet. Unter Settings → Model → Fast → Save zum Template-Standard `gpt-4.1-mini` wechseln; bestehende persönliche Deployment-Auswahlen bleiben sonst erhalten. Auch Mini braucht verfügbares Azure-Kontingent. Bleiben die Fehler: TPM/RPM, andere Verbraucher und Deployment-Kapazität prüfen. Vor einem manuellen neuen Auftrag bereits freigegebene Jira-Änderungen prüfen. |
| Fehler im Chat nachvollziehen | Knopf **Chat log** im Kopf lädt ein Log (`.log`) des Chats herunter: System-Prompt, Nachrichten, Tool-Aufrufe, Ergebnisse, Fehler. Zugangsdaten werden maskiert, Ticket- und Tabelleninhalt bleibt enthalten – vor dem Teilen prüfen. Nur im Speicher: letzte 10 Chats pro Nutzer, nach Neustart weg. Endpunkt: `GET /jira/api/chatlog?chat_id=` |
| Nachrichtenfeld lässt sich ohne Text absenden | behoben ab v0.2.3 (Prüfung wird beim App-Start in die Chat-Oberfläche eingesetzt) |
