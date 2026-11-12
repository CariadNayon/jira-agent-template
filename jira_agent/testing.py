"""Test-Helfer: eigene Tools ohne echtes Jira, Databricks oder Modell testen.

    from jira_agent.testing import FakeJira, run_tool

    def test_mein_tool():
        jira = FakeJira(issues={"ABC-1": {"summary": "Bremse quietscht"}})
        result = run_tool("jira_add_label", jira=jira, issue_key="ABC-1", label="geprueft")
        assert result == {"status": "OK"}
        assert "geprueft" in jira.issues["ABC-1"]["labels"]

run_tool bestätigt Schreib-Tools automatisch ("ja <CODE>"), damit man nur die eigentliche Logik testet.
Alle Aufrufe an Jira stehen in jira.calls, z. B. [("PUT", "/issue/ABC-1", {...})].
"""
from __future__ import annotations

import json
import re

from jira_agent.adapter import RunContext, execute
from jira_agent.jira_client import JiraClient
from jira_agent.tools import ToolContext, load_tools

_DEFAULT_TRANSITIONS = [{"id": "11", "name": "Start", "to": "In Arbeit"},
                        {"id": "21", "name": "Erledigen", "to": "Erledigt"}]


class FakeResponse:
    def __init__(self, status_code: int, data=None):
        self.status_code = status_code
        self._data = data
        self.content = b"" if data is None else json.dumps(data).encode()
        self.text = self.content.decode()
        self.headers = {"Content-Type": "application/json"}

    def json(self):
        return self._data


class FakeJira(JiraClient):
    """Jira im Speicher. issues: {"ABC-1": {"summary": ..., "status": ..., ...}} (vereinfachte Felder).

    Die Suche ignoriert JQL und liefert alle Tickets – für Tests reicht das meist.
    """

    def __init__(self, issues: dict | None = None, users: list[dict] | None = None,
                 transitions: list[dict] | None = None, create_fields: list[dict] | None = None,
                 issue_types: list[dict] | None = None):
        super().__init__("https://jira.example/rest/api/2", "fake-token")
        self.issues = {k: {"summary": "", "status": "Offen", "labels": [], "comments": [], "links": [],
                           "worklogs": [], **v} for k, v in (issues or {}).items()}
        self.users = users or [{"name": "max.muster", "displayName": "Muster, Max"}]
        self.issue_types = issue_types or [{"id": "10001", "name": "Task", "subtask": False}]
        self.creation_fields = create_fields if create_fields is not None else [
            {"fieldId": "summary", "name": "Summary", "required": True, "schema": {"type": "string"}},
            {"fieldId": "description", "name": "Description", "required": False, "schema": {"type": "string"}},
            {"fieldId": "priority", "name": "Priority", "required": False,
             "allowedValues": [{"id": "1", "name": "High"}, {"id": "2", "name": "Low"}]},
            {"fieldId": "labels", "name": "Labels", "required": False},
            {"fieldId": "customfield_10010", "name": "Team", "required": False},
        ]
        self.transition_options = transitions or _DEFAULT_TRANSITIONS
        self.calls: list[tuple] = []

    def request(self, method: str, path: str, **kwargs) -> FakeResponse:
        body = kwargs.get("json") or {}
        self.calls.append((method, path, body or kwargs.get("params")))
        m = re.fullmatch(r"/issue/([A-Z][A-Z0-9_]+-\d+)(/\w+)?", path)
        key, sub = (m.group(1), m.group(2)) if m else (None, None)
        if key and key not in self.issues:
            return FakeResponse(404, {"errorMessages": ["Issue Does Not Exist"]})
        issue = self.issues.get(key) if key else None

        if path.startswith("/issue/createmeta/"):
            rows = self.creation_fields if path.rsplit("/", 1)[-1].isdigit() else self.issue_types
            params = kwargs["params"]
            start, size = params["startAt"], params["maxResults"]
            return FakeResponse(200, {"values": rows[start:start + size], "isLast": start + size >= len(rows)})
        if path == "/priority":
            return FakeResponse(200, [{"id": "1", "name": "High"}, {"id": "2", "name": "Low"}])
        if path == "/issueLinkType":
            return FakeResponse(200, {"issueLinkTypes": [
                {"id": "1", "name": "Blocks", "outward": "blocks", "inward": "is blocked by"}]})
        if sub == "/editmeta" and method == "GET":
            return FakeResponse(200, {"fields": {f["fieldId"]: f for f in self.creation_fields}})
        if path == "/myself":
            return FakeResponse(200, self.users[0])
        if path == "/search":
            found = [self._jira_issue(k) for k in self.issues]
            start=kwargs["params"].get("startAt",0)
            return FakeResponse(200, {"total":len(found),"startAt":start,
                                      "issues":found[start:start+kwargs["params"]["maxResults"]]})
        if path == "/user/search":
            return FakeResponse(200, self.users)
        if path == "/project":
            keys = sorted({k.split("-")[0] for k in self.issues})
            return FakeResponse(200, [{"key": k, "name": k} for k in keys])
        if path == "/field":
            return FakeResponse(200, [{"id": "summary", "name": "Summary"}])
        if path == "/issue" and method == "POST":
            project = body["fields"]["project"]["key"]
            number = max([int(k.split("-")[-1]) for k in self.issues if k.startswith(project + "-")] or [0]) + 1
            new_key = f"{project}-{number}"
            fields = {k: v for k, v in body["fields"].items() if k not in ("project",)}
            self.issues[new_key] = {"summary": fields.get("summary", ""), "status": "Offen", "labels": [],
                                    "comments": [], "links": [], "worklogs": [], "fields": fields,
                                    **{k: (v["name"] if isinstance(v, dict) and "name" in v else v)
                                       for k, v in fields.items() if k != "components"},
                                    "components": [c["name"] for c in fields.get("components", [])]}
            return FakeResponse(201, {"key": new_key})
        if path == "/issueLink" and method == "POST":
            self.issues[body["outwardIssue"]["key"]]["links"].append((body["type"]["name"], body["inwardIssue"]["key"]))
            return FakeResponse(201)
        if issue is not None:
            if sub is None and method == "GET":
                return FakeResponse(200, self._jira_issue(key))
            if sub is None and method == "PUT":
                for label in (body.get("update") or {}).get("labels", []):
                    issue["labels"].append(label["add"])
                for name, value in (body.get("fields") or {}).items():
                    issue[name] = value["name"] if isinstance(value, dict) and "name" in value else value
                return FakeResponse(204)
            if sub == "/assignee":
                issue["assignee"] = body["name"]
                return FakeResponse(204)
            if sub == "/comment" and method == "POST":
                issue["comments"].append(body["body"])
                return FakeResponse(201, {})
            if sub == "/comment":
                return FakeResponse(200, {"comments": [{"author": {"displayName": "Test"}, "body": c}
                                                       for c in issue["comments"][:kwargs["params"]["maxResults"]]]})
            if sub == "/transitions" and method == "GET":
                return FakeResponse(200, {"transitions": [{"id": t["id"], "name": t["name"], "to": {"name": t["to"]}, "fields": t.get("fields", {})}
                                                          for t in self.transition_options]})
            if sub == "/transitions":
                target = next(t for t in self.transition_options if t["id"] == body["transition"]["id"])
                issue["status"] = target["to"]
                return FakeResponse(204)
            if sub == "/worklog":
                issue["worklogs"].append(body["timeSpent"])
                return FakeResponse(201, {})
        return FakeResponse(400, {"errorMessages": [f"FakeJira kennt {method} {path} nicht"]})

    def _jira_issue(self, key: str) -> dict:
        i = self.issues[key]
        return {"key": key, "fields": {
            "summary": i.get("summary"), "description": i.get("description", ""),
            "status": {"name": i.get("status")}, "priority": {"name": i.get("priority")} if i.get("priority") else None,
            "assignee": {"name": i["assignee"]} if i.get("assignee") else None,
            "components": [{"name": c} for c in i.get("components", [])], "labels": list(i["labels"]),
            "updated": i.get("updated")}}


class FakeSql:
    """Ersatz für ctx.sql: liefert immer das angegebene Ergebnis und merkt sich die Abfragen."""

    def __init__(self, columns: list[str], rows: list[list], tables: dict | None = None):
        self.columns, self.rows, self.tables = columns, rows, tables or {}
        self.queries: list[str] = []

    def query(self, sql: str, row_limit: int | None = None, timeout_s: int = 120) -> dict:
        self.queries.append(sql)
        rows = self.rows[: row_limit or len(self.rows)]
        return {"columns": self.columns, "rows": rows, "row_count": len(rows), "truncated": False}

    def describe(self, full_name: str) -> dict:
        return {"table": full_name, "columns": self.tables.get(full_name, [{"name": c} for c in self.columns])}


class FakeFiles:
    """Ersatz für ctx.files: Dateien landen in self.files {name: bytes}."""

    def __init__(self):
        self.files: dict[str, tuple[str, bytes]] = {}

    def put(self, name: str, mime: str, data: bytes) -> str:
        self.files[name] = (mime, data)
        return f"/jira/files/{name}"


def run_tool(name: str, *, jira=None, sql=None, files=None, uploads=None, selected_tables=(), vision: bool=False, confirm: bool = True,
             **args) -> dict:
    """Führt ein Tool wie im Agenten aus. Schreib-Tools werden mit confirm=True automatisch bestätigt.

    uploads: z. B. UploadSink("test@example.com") aus jira_agent.state, vorher mit .put(name, mime, bytes) befüllt.
    """
    tools = load_tools()
    if name not in tools:
        raise KeyError(f"Tool {name} nicht gefunden. Vorhanden: {sorted(tools)}")
    t = tools[name]
    ctx = ToolContext(jira=jira, sql=sql, files=files, uploads=uploads, selected_tables=list(selected_tables), vision=vision)
    rc = RunContext(ctx, b"test-secret", "")
    result = execute(t, rc, dict(args))
    if t.write and confirm and result.get("status") == "BESTAETIGUNG_NOETIG":
        rc.last_user_text = f"ja {result['code']}"
        result = execute(t, rc, {**args, "confirmation_code": result["code"]})
    return result
