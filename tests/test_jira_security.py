"""Tests für die Schutzmechanismen des Jira-Agenten (ohne Databricks- oder Jira-Verbindung)."""
from types import SimpleNamespace

import pytest

from jira_agent import state as state_mod
from jira_agent.adapter import RunContext, execute
from jira_agent.data import SqlRunner, check_readonly_sql
from jira_agent.tools import Tool, ToolContext

ALLOWED = ["main.sales.orders"]


@pytest.mark.parametrize("sql", [
    "SELECT ai_query('endpoint', 'x') FROM main.sales.orders",
    "SELECT http_request(conn => 'c', method => 'GET', path => '/') FROM main.sales.orders",
    "SELECT secret('scope', 'key')",
    "SELECT try_secret('scope', 'key')",
    "SELECT reflect('java.lang.Runtime', 'getRuntime')",
    "SELECT main.tools.my_udf(amount) FROM main.sales.orders",
    "SELECT main.tools.hash(amount) FROM main.sales.orders",
    "SELECT ai_classify(text, array('a', 'b')) FROM main.sales.orders",
    "SELECT (SELECT max(x) FROM main.hr.salaries) FROM main.sales.orders",
])
def test_readonly_sql_blocks_side_effects_and_foreign_tables(sql):
    with pytest.raises(ValueError):
        check_readonly_sql(sql, ALLOWED)


def test_readonly_sql_allows_builtin_functions():
    sql = ("SELECT date_part('year', d) AS y, date_trunc('month', d) AS m, count(*) AS n, "
           "coalesce(sum(amount), 0) AS total FROM main.sales.orders GROUP BY 1, 2")
    assert check_readonly_sql(sql, ALLOWED) == sql


def _write_tool(calls):
    return Tool("jira_comment", "", {}, ("issue_key",), lambda ctx, **kw: calls.append(kw) or {"status": "OK"},
                write=True)


def test_write_tool_requires_code_from_user_message():
    calls = []
    t = _write_tool(calls)
    rc = RunContext(ToolContext(), b"secret", "kommentiere ABC-1")
    first = execute(t, rc, {"issue_key": "ABC-1"})
    assert first["status"] == "BESTAETIGUNG_NOETIG" and not calls

    code = first["code"]
    # Modell schickt den Code, der Nutzer hat ihn aber nicht bestätigt.
    assert execute(t, rc, {"issue_key": "ABC-1", "confirmation_code": code})["status"] == "BESTAETIGUNG_NOETIG"
    # Bestätigter Code gilt nicht für andere Argumente.
    rc_ok = RunContext(ToolContext(), b"secret", f"ja {code.lower()}")
    assert execute(t, rc_ok, {"issue_key": "ABC-2", "confirmation_code": code})["status"] == "BESTAETIGUNG_NOETIG"
    assert not calls

    assert execute(t, rc_ok, {"issue_key": "ABC-1", "confirmation_code": code}) == {"status": "OK"}
    assert calls == [{"issue_key": "ABC-1"}]


def test_session_expires_absolutely_and_is_purged(monkeypatch):
    now = [1_000_000.0]
    monkeypatch.setattr(state_mod.time, "time", lambda: now[0])
    monkeypatch.setattr(state_mod, "_users", {})
    s = state_mod.user_state("a@x.de")
    s.creds["jira_token"] = "t"
    state_mod.user_state("b@x.de")
    for st in state_mod._users.values():
        st.created = now[0]

    now[0] += state_mod._CRED_TTL - 1
    assert state_mod.user_state("a@x.de").creds  # regelmäßige Zugriffe verlängern nicht
    now[0] += 2
    assert not state_mod.user_state("a@x.de").creds
    assert "b@x.de" not in state_mod._users


def test_prepare_rejects_missing_identity_in_app(monkeypatch):
    from jira_agent.runtime import prepare

    monkeypatch.setenv("DATABRICKS_APP_NAME", "agent-jira-v2")
    with pytest.raises(PermissionError):
        prepare({}, [])


def _resp(state, rows=None, next_chunk=None, truncated=False):
    from databricks.sdk.service.sql import StatementState

    return SimpleNamespace(
        statement_id="st1",
        status=SimpleNamespace(state=getattr(StatementState, state), error=None),
        manifest=SimpleNamespace(schema=SimpleNamespace(columns=[SimpleNamespace(name="x")]), truncated=truncated),
        result=SimpleNamespace(data_array=rows, next_chunk_index=next_chunk))


def test_sql_runner_reads_all_chunks_up_to_limit():
    chunks = {1: SimpleNamespace(data_array=[["2"], ["3"]], next_chunk_index=2),
              2: SimpleNamespace(data_array=[["4"]], next_chunk_index=None)}
    api = SimpleNamespace(execute_statement=lambda **kw: _resp("SUCCEEDED", [["1"]], next_chunk=1),
                          get_statement_result_chunk_n=lambda sid, i: chunks[i])
    res = SqlRunner(SimpleNamespace(statement_execution=api), "wh", row_limit=3).query("SELECT 1")
    assert res["rows"] == [["1"], ["2"], ["3"]] and res["truncated"]


def test_sql_runner_cancels_on_timeout(monkeypatch):
    import jira_agent.data as data_mod

    cancelled = []
    api = SimpleNamespace(execute_statement=lambda **kw: _resp("RUNNING"),
                          get_statement=lambda sid: _resp("RUNNING"),
                          cancel_execution=cancelled.append)
    monkeypatch.setattr(data_mod.time, "sleep", lambda s: None)
    res = SqlRunner(SimpleNamespace(statement_execution=api), "wh").query("SELECT 1", timeout_s=0)
    assert res["error"] == "TIMEOUT" and cancelled == ["st1"]
