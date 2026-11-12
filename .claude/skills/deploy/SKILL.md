---
name: deploy
description: "Jira-Agent nach Databricks deployen bzw. neu starten. Verwenden bei: 'deploy', 'hochladen', 'veröffentlichen', 'App aktualisieren', 'App already exists', Fehler nach dem Deploy, Logs ansehen."
---

# Deployen

App-Name, Secret und Warehouse stehen **nur** in `databricks.yml` unter `variables` (Standardwerte). Die App liest sie auch zur Laufzeit als Fallback. Nicht in andere Dateien kopieren. Einmalig überschreiben: `uv run deploy --var app_name=…`.

Optionen: `--profile <name>`, `--target prod`, `--var NAME=WERT`, `--no-start`, `--bind`. Ohne Skript geht auch `databricks bundle deploy` + `databricks bundle run agent_openai_agents_sdk`.

## Ablauf

1. **Profil ermitteln**: `.env` lesen (`DATABRICKS_CONFIG_PROFILE`). Fehlt `.env` → Skill **einrichten**.
2. **Anmeldung prüfen**: `databricks auth profiles` – steht beim Profil `Valid: NO`:
   `databricks auth login --profile <profil>` (öffnet den Browser; Nutzer meldet sich an).
3. **Tests**: `uv run pytest tests -q` – nur bei Grün weiter.
4. **Prüfen ohne Upload**: `uv run deploy --check`
5. **Deployen**: `uv run deploy` – lädt hoch, startet die App neu und zeigt am Ende die URL.
6. Dem Nutzer sagen: Seite der App mit **Strg+Shift+R** neu laden; Jira-Token ggf. neu eintragen (liegt nur im Speicher).

Optionen siehe oben.

## Fehler

| Meldung | Lösung |
|---|---|
| `An app with the same name already exists` | Nutzer fragen: bestehende App übernehmen → `uv run deploy --bind`; oder neuen Namen in `databricks.yml` (`variables.app_name.default`) setzen. |
| `cannot configure default credentials` / Profil ungültig | `databricks auth login --profile <profil>` |
| Secret/Warehouse nicht gefunden oder keine Rechte | Werte in `databricks.yml` (`variables`) prüfen; der Nutzer braucht selbst Zugriff auf Secret Scope (MANAGE) und Warehouse (CAN_MANAGE), um sie der App zu geben. |
| App startet nicht / Fehler im Chat | Logs: `databricks apps logs <app_name> --profile <profil>` |

## Erste Einrichtung einer neuen App

In `databricks.yml` unter `variables` den Standardwert von `app_name` ändern (Kleinbuchstaben, Ziffern, Bindestriche, z. B. `agent-jira-team-x`), ggf. `secret_scope`, `secret_key`, `warehouse_id`. Dann `uv run deploy`. Die App wird angelegt. Danach im Databricks-UI unter **Compute → Apps → <Name> → Permissions** festlegen, wer die App nutzen darf.

## GitHub Actions

`.github/workflows/deploy.yml` führt `uv run deploy --target prod` aus (manuell über den Actions-Tab). Voraussetzungen stehen oben in der Datei.
