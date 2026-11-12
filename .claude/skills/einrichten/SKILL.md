---
name: einrichten
description: "Lokale Entwicklungsumgebung für den Jira-Agenten einrichten (Databricks-Anmeldung, .env, MLflow-Experiment). Verwenden bei: erster Start, 'einrichten', 'setup', fehlende .env, Anmeldefehler."
---

# Einrichten

## Voraussetzungen

- `uv` (https://docs.astral.sh/uv/getting-started/installation/), Version ≥ 0.9.17 (`uv self update`)
- Databricks CLI (https://docs.databricks.com/aws/en/dev-tools/cli/install)
- Node.js 20+ (für die Chat-Oberfläche lokal)

## Ablauf

1. **Existiert `.env`?** Dann ist schon eingerichtet: Profil aus `DATABRICKS_CONFIG_PROFILE` lesen und nur die Anmeldung prüfen (`databricks auth profiles`, bei `Valid: NO` → `databricks auth login --profile <profil>`). Fertig.
2. **Sonst**: Nutzer nach dem Workspace fragen (URL, z. B. `https://adb-….azuredatabricks.net`) und einrichten:

```bash
uv run quickstart --host <workspace-url> --skip-lakebase
# oder mit vorhandenem CLI-Profil:
uv run quickstart --profile <profil> --skip-lakebase
```

   Das legt `.env` an, meldet an und erstellt ein MLflow-Experiment für Traces.
   **Nicht** `--app-name` verwenden – der App-Name steht in `databricks.yml` (`variables.app_name`).
3. **Lokal starten**: Skill **run-locally**.

Hinweis: Lokal läuft alles mit den Rechten des angemeldeten Nutzers; der Team-Key für Azure OpenAI wird aus dem Secret Scope in `databricks.yml` gelesen (der Nutzer braucht dort Leserecht).
