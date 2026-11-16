"""Eingebaute Daten-Tools: nur lesend, nur freigegebene Tabellen, mit den Rechten des Nutzers."""
from __future__ import annotations

from jira_agent.data import check_readonly_sql, normalize_table
from jira_agent.tools import ToolContext, tool


def check_selected(ctx: ToolContext, table: str) -> str:
    full = normalize_table(table)
    if full not in {normalize_table(t) for t in ctx.selected_tables}:
        raise ValueError(f"Table {full} is not enabled.")
    return full


@tool(needs=["sql"])
def list_selected_tables(ctx: ToolContext) -> dict:
    """Lists the tables enabled by the user in Settings."""
    return {"tables": ctx.selected_tables}


@tool(needs=["sql"])
def describe_table(ctx: ToolContext, table: str) -> dict:
    """Shows columns, types and descriptions for an enabled table.

    table: catalog.schema.table"""
    return ctx.sql.describe(check_selected(ctx, table))


@tool(needs=["sql"])
def run_readonly_sql(ctx: ToolContext, sql: str) -> dict:
    """Executes exactly one read-only SELECT on enabled tables (at most 200 rows by default).

    sql: SELECT with fully qualified table names (catalog.schema.table)"""
    return ctx.sql.query(check_readonly_sql(sql, ctx.selected_tables))
