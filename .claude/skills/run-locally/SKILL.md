---
name: run-locally
description: "Jira-Agent lokal starten und testen. Verwenden bei: 'lokal starten', 'run locally', 'start server', 'localhost', 'testen', Fehler beim lokalen Start."
---

# Lokal starten und testen

## Tests (immer zuerst)

```bash
uv run pytest tests -q
```

Läuft ohne Databricks, Jira oder Modell (FakeJira/FakeSql aus `jira_agent/testing.py`).

## App starten

```bash
uv run start-app
```

Chat unter http://localhost:8000, Zahnrad oben rechts für Jira-Token, Regeln und Tabellen.

Optionen (werden an den Server durchgereicht):

```bash
uv run start-server --reload      # Neustart bei Code-Änderungen
uv run start-server --port 8001   # anderer Port
```

Immer nur **1 Worker** – `--workers` > 1 wird abgelehnt (Sitzungsdaten liegen im Speicher).

## API direkt testen

```bash
curl -X POST http://localhost:8000/invocations -H "Content-Type: application/json" \
  -d '{ "input": [{ "role": "user", "content": "Welche Tabellen sind freigegeben?" }] }'
```

## Probleme

| Problem | Lösung |
|---|---|
| Port belegt | `--port 8001` oder alten Prozess beenden |
| Anmeldefehler | `.env` prüfen; `databricks auth login --profile <profil>`; Skill **einrichten** |
| `Module not found` | `uv sync` |
| MLflow-Experiment nicht gefunden | In `.env` `MLFLOW_TRACKING_URI="databricks://<profil>"` setzen |
| Warnung `exclude-newer = "7 days"` | uv aktualisieren: `uv self update` |

## Weiter

- Neues Tool: Skill **neues-tool**
- Deployen: Skill **deploy**
