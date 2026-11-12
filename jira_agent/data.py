"""Lesender Tabellenzugriff mit den Rechten des Nutzers (on-behalf-of-user).

Zwei Schutzschichten:
1. check_readonly_sql: genau ein SELECT, nur auf freigegebenen, voll qualifizierten Tabellen.
2. Der App-Scope sql:restricted-query erlaubt serverseitig nur lesende Abfragen.
"""
from __future__ import annotations

import time

import sqlglot
from sqlglot import exp

_FORBIDDEN = tuple(getattr(exp, n) for n in (
    "Insert", "Update", "Delete", "Drop", "Create", "Merge", "Alter", "Command", "TruncateTable", "Copy")
    if hasattr(exp, n))


def normalize_table(name: str) -> str:
    return ".".join(p.strip("` ").lower() for p in name.split("."))


def check_readonly_sql(sql: str, allowed_tables: list[str]) -> str:
    allowed = {normalize_table(t) for t in allowed_tables}
    try:
        statements = [s for s in sqlglot.parse(sql, read="databricks") if s is not None]
    except sqlglot.errors.ParseError as e:
        raise ValueError(f"SQL nicht lesbar: {str(e)[:200]}") from e
    if len(statements) != 1:
        raise ValueError("Genau eine Abfrage erlaubt.")
    stmt = statements[0]
    if not isinstance(stmt, exp.Query) or (_FORBIDDEN and stmt.find(*_FORBIDDEN)):
        raise ValueError("Nur lesende SELECT-Abfragen sind erlaubt.")
    cte_names = {c.alias_or_name.lower() for c in stmt.find_all(exp.CTE)}
    for t in stmt.find_all(exp.Table):
        if not t.name:
            raise ValueError("Tabellenfunktionen sind nicht erlaubt.")
        if not t.db and t.name.lower() in cte_names:
            continue
        if not (t.catalog and t.db):
            raise ValueError(f"Tabelle {t.name} bitte voll qualifiziert angeben (catalog.schema.table).")
        full = f"{t.catalog}.{t.db}.{t.name}".lower()
        if full not in allowed:
            raise ValueError(f"Tabelle {full} ist nicht freigegeben.")
    return sql


class SqlRunner:
    """Führt Abfragen über das Statement-Execution-API mit dem WorkspaceClient des Nutzers aus."""

    def __init__(self, user_client, warehouse_id: str, row_limit: int = 200):
        self.w = user_client
        self.warehouse_id = warehouse_id
        self.row_limit = row_limit

    def __repr__(self) -> str:
        return f"SqlRunner(warehouse_id={self.warehouse_id!r})"

    def query(self, sql: str, row_limit: int | None = None, timeout_s: int = 120) -> dict:
        from databricks.sdk.service.sql import StatementState

        resp = self.w.statement_execution.execute_statement(
            statement=sql, warehouse_id=self.warehouse_id, wait_timeout="30s",
            row_limit=row_limit or self.row_limit)
        deadline = time.time() + timeout_s
        while resp.status.state in (StatementState.PENDING, StatementState.RUNNING) and time.time() < deadline:
            time.sleep(2)
            resp = self.w.statement_execution.get_statement(resp.statement_id)
        if resp.status.state != StatementState.SUCCEEDED:
            err = resp.status.error.message if resp.status.error else ""
            return {"error": resp.status.state.value, "details": (err or "")[:500]}
        columns = [c.name for c in resp.manifest.schema.columns]
        rows = (resp.result.data_array if resp.result else None) or []
        return {"columns": columns, "rows": rows, "row_count": len(rows),
                "truncated": bool(resp.manifest.truncated)}

    def describe(self, full_name: str) -> dict:
        t = self.w.tables.get(full_name)
        return {"table": t.full_name, "comment": t.comment,
                "columns": [{"name": c.name, "type": c.type_text, "comment": c.comment} for c in t.columns or []]}
