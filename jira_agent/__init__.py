"""Jira-Agent-Erweiterung für die Databricks-Agent-Vorlage.

config.yaml  – zentrale Standardwerte (Jira-URL, Azure, Warehouse, Standardregeln)
llm.py       – Modell-Provider (Azure Team-Key / eigener Key) für das OpenAI Agents SDK
tools/       – Tool-Registry (@tool). Neue Datei = neues Tool, write=True = Bestätigung nötig
adapter.py   – macht aus der Registry FunctionTools des Agents SDK, erzwingt 'ja <CODE>'
runtime.py   – baut pro Anfrage den Agenten mit den Daten des angemeldeten Nutzers
web.py       – Endpunkte für Zahnrad (Keys, Einstellungen, Unity Catalog) und Dateien
"""
from pathlib import Path

import yaml

CFG = yaml.safe_load((Path(__file__).parent / "config.yaml").read_text(encoding="utf-8"))


def _bundle_defaults() -> dict:
    """Standardwerte der Variablen aus databricks.yml (app_name, secret_scope, secret_key, warehouse_id)."""
    path = Path(__file__).parent.parent / "databricks.yml"
    if not path.exists():
        return {}
    variables = (yaml.safe_load(path.read_text(encoding="utf-8")) or {}).get("variables") or {}
    return {name: str(v.get("default", "")) for name, v in variables.items() if isinstance(v, dict)}


BUNDLE = _bundle_defaults()
