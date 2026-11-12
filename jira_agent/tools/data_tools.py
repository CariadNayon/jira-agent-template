"""Eingebaute Daten-Tools: nur lesend, nur freigegebene Tabellen, mit den Rechten des Nutzers."""
from __future__ import annotations

from jira_agent.data import check_readonly_sql, normalize_table
from jira_agent.tools import ToolContext, tool


def check_selected(ctx: ToolContext, table: str) -> str:
    full = normalize_table(table)
    if full not in {normalize_table(t) for t in ctx.selected_tables}:
        raise ValueError(f"Tabelle {full} ist nicht freigegeben.")
    return full


@tool("Listet die Tabellen, die der Nutzer im Zahnrad freigegeben hat.", needs=["sql"])
def list_selected_tables(ctx: ToolContext) -> dict:
    return {"tables": ctx.selected_tables}


@tool("Zeigt Spalten, Typen und Beschreibungen einer freigegebenen Tabelle.",
      {"table": {"type": "string", "description": "catalog.schema.table"}}, ["table"], needs=["sql"])
def describe_table(ctx: ToolContext, table: str) -> dict:
    return ctx.sql.describe(check_selected(ctx, table))


@tool("Führt genau ein lesendes SELECT auf freigegebenen Tabellen aus (max. 200 Zeilen).",
      {"sql": {"type": "string"}}, ["sql"], needs=["sql"])
def run_readonly_sql(ctx: ToolContext, sql: str) -> dict:
    return ctx.sql.query(check_readonly_sql(sql, ctx.selected_tables))
