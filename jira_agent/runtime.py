"""Baut pro Anfrage den Agenten mit Identität, Keys, Einstellungen und Rechten des angemeldeten Nutzers."""
from __future__ import annotations

import os
import re
from typing import Mapping

from jira_agent import CFG
from jira_agent.adapter import RunContext, build_function_tools
from jira_agent.data import SqlRunner
from jira_agent.jira_client import JiraClient
from jira_agent.llm import build_model
from jira_agent.settings_store import SettingsStore
from jira_agent.state import FileSink, UserState, user_state
from jira_agent.tools import ToolContext

WAREHOUSE_ID = os.environ.get("WAREHOUSE_ID") or CFG["data"]["warehouse_id"]

DEFAULT_SETTINGS = {
    "agent_name": "",
    "rules": CFG["agent"]["default_rules"].strip(),
    "selected_tables": [],
    "llm_provider": CFG["llm"]["provider"],
    "azure_endpoint": "",
    "azure_deployment": "",
    "azure_api_version": "",
}

INSTRUCTIONS = """Du bist {name}, ein persönlicher Jira- und Daten-Assistent. Antworte auf Deutsch, kurz und klar.

Regeln des Nutzers:
{rules}

Jira: {jira}
Freigegebene Tabellen (nur diese, nur lesend, immer voll qualifiziert als catalog.schema.table):
{tables}

Vorgehen:
- Jira-Tickets suchst du mit jira_search (JQL), Details holst du mit jira_get_issue.
- Für Daten: zuerst describe_table, dann run_readonly_sql mit genau einem SELECT.
- Diagramme erstellst du mit create_chart, Dateien mit export_file. Gib das Feld "markdown"
  aus dem Ergebnis unverändert in deiner Antwort aus, damit Bild bzw. Download-Link erscheinen.
- Schreib-Tools rufst du zuerst ohne confirmation_code auf. Das Tool liefert einen Code.
  Zeige dem Nutzer genau, was passieren soll, und den Code, und bitte um "ja <CODE>".
  Erst danach rufst du das Tool mit diesem confirmation_code erneut auf.
- Nenne bei jeder vorgeschlagenen Aktion die Regel, nach der du handelst.
- Erfinde keine Tickets oder Zahlen. Meldet ein Tool einen Fehler, sag das ehrlich.
"""


def default_agent_name(display_name: str | None) -> str:
    """'Lenz, Nayon' -> 'Nayons Jira Agent', 'Klaus Meier' -> 'Klaus’ Jira Agent', ohne Namen -> 'Jira Agent'."""
    name = re.sub(r"\(.*?\)", "", display_name or "").strip()
    first = name.split(",", 1)[1].strip() if "," in name else name
    first = first.split()[0] if first.split() else ""
    if not first:
        return "Jira Agent"
    suffix = "’" if first[-1].lower() in "sxzß" else "s"
    return f"{first}{suffix} Jira Agent"


def agent_name(state: UserState, settings: dict) -> str:
    return (settings.get("agent_name") or "").strip() or default_agent_name(state.jira_display_name)


def identity(headers: Mapping[str, str]) -> tuple[str | None, str | None]:
    h = {k.lower(): v for k, v in (headers or {}).items()}
    return h.get("x-forwarded-email"), h.get("x-forwarded-access-token")


def user_client(token: str):
    """WorkspaceClient mit den Rechten des angemeldeten Nutzers (User Authorization der App)."""
    from databricks.sdk import WorkspaceClient

    return WorkspaceClient(token=token, auth_type="pat")


def load_settings(state: UserState, email: str, token: str | None) -> dict:
    if state.settings is None:
        loaded = {}
        if token and email and email != "local":
            try:
                loaded = SettingsStore(user_client(token), email).load()
            except Exception:
                loaded = {}
        state.settings = {**DEFAULT_SETTINGS, **loaded}
    return state.settings


def last_user_text(messages: list[dict]) -> str:
    for m in reversed(messages):
        if m.get("role") == "user":
            c = m.get("content")
            if isinstance(c, str):
                return c
            if isinstance(c, list):
                return " ".join(p.get("text", "") for p in c if isinstance(p, dict))
    return ""


def prepare(headers: Mapping[str, str], messages: list[dict]):
    """Liefert (agent, run_context) für Runner.run(agent, messages, context=run_context)."""
    from agents import Agent

    email, token = identity(headers)
    email = email or "local"
    state = user_state(email)
    settings = load_settings(state, email, token)
    tables = list(settings["selected_tables"])
    w = user_client(token) if token else None
    tool_ctx = ToolContext(
        jira=JiraClient(CFG["jira"]["base_url"], state.creds["jira_token"]) if state.creds.get("jira_token") else None,
        sql=SqlRunner(w, WAREHOUSE_ID, CFG["data"]["row_limit"]) if (w and tables) else None,
        files=FileSink(email),
        selected_tables=tables,
    )
    instructions = INSTRUCTIONS.format(
        name=agent_name(state, settings),
        rules=settings["rules"] or "(keine)",
        jira=f"verbunden als {state.jira_user}" if tool_ctx.jira else
             "nicht verbunden – bitte den Nutzer bitten, oben rechts über das Zahnrad seinen Jira-Token einzutragen",
        tables="\n".join(f"- {t}" for t in tables) or "(keine – Tabellen lassen sich über das Zahnrad freigeben)",
    )
    model = build_model(settings["llm_provider"], CFG["llm"], settings, state.creds)
    agent = Agent(name="Jira Agent", instructions=instructions, model=model, tools=build_function_tools(tool_ctx))
    return agent, RunContext(tool_ctx, state.secret, last_user_text(messages))
