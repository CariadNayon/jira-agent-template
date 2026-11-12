"""Schlanker Jira-REST-Client (Data Center, Personal Access Token). Der Token lebt nur in dieser Instanz."""
from __future__ import annotations

import re

import requests

KEY_RE = re.compile(r"[A-Z][A-Z0-9_]+-\d+")
PROJECT_RE = re.compile(r"[A-Z][A-Z0-9_]+")
USER_RE = re.compile(r"[\w.\-@]+")


class JiraError(Exception):
    pass


class JiraClient:
    def __init__(self, base_url: str, token: str, timeout: int = 30):
        if not token:
            raise JiraError("Kein Jira-Token angegeben.")
        self.base_url = base_url.rstrip("/")
        self._headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
        self._timeout = timeout

    def __repr__(self) -> str:  # Token nie ausgeben (auch nicht in Traces)
        return f"JiraClient(base_url={self.base_url!r})"

    def request(self, method: str, path: str, **kwargs) -> requests.Response:
        return requests.request(method, f"{self.base_url}{path}", headers=self._headers,
                                timeout=self._timeout, **kwargs)

    def myself(self) -> dict:
        try:
            r = self.request("GET", "/myself")
        except requests.RequestException as e:
            raise JiraError(f"Jira nicht erreichbar: {type(e).__name__}") from None
        if r.status_code != 200 or "json" not in r.headers.get("Content-Type", ""):
            raise JiraError(f"Jira-Anmeldung fehlgeschlagen (HTTP {r.status_code}).")
        return r.json()

    @staticmethod
    def check_key(issue_key: str) -> str:
        key = (issue_key or "").strip().upper()
        if not KEY_RE.fullmatch(key):
            raise ValueError(f"Ungültiger Ticket-Key: {key!r}")
        return key

    @staticmethod
    def check_user(user_name: str) -> str:
        if not USER_RE.fullmatch(user_name or ""):
            raise ValueError(f"Ungültiger Nutzername: {user_name!r}")
        return user_name

    @staticmethod
    def check_project(project: str) -> str:
        key = (project or "").strip().upper()
        if not PROJECT_RE.fullmatch(key):
            raise ValueError("Ungültiger Projekt-Key.")
        return key

    @staticmethod
    def check_text(text: str, name: str, limit: int) -> str:
        if not isinstance(text, str) or not text.strip() or len(text) > limit:
            raise ValueError(f"{name}: 1–{limit} Zeichen erforderlich.")
        return text

    def resolve_user(self, user_name: str) -> str:
        """@me bezeichnet ausschließlich den Besitzer des Jira-Tokens dieser Sitzung."""
        if user_name == "@me":
            user_name = self.myself().get("name") or ""
        return self.check_user(user_name)

    def issue_url(self, issue_key: str) -> str:
        return self.base_url.split("/rest/api/", 1)[0] + "/browse/" + self.check_key(issue_key)

    def _metadata_pages(self, path: str) -> list[dict]:
        """Jira Data Center 8.4+: paginierte Create-Metadaten, ohne stilles Abschneiden."""
        result, start = [], 0
        while start < 1000:
            page = self._call("GET", path, params={"startAt": start, "maxResults": 100})
            values = page.get("values")
            if not isinstance(values, list):
                raise JiraError("Unerwartetes Format der Jira-Metadaten (values fehlt).")
            result.extend(values)
            next_start = start + len(values)
            total = page.get("total")
            if (page.get("isLast") is True
                    or (total is not None and next_start >= total)
                    or ("isLast" not in page and total is None
                        and len(values) < page.get("maxResults", 100))):
                return result
            if not values:
                raise JiraError("Jira-Metadaten konnten nicht vollständig geladen werden.")
            start = next_start  # Jira may enforce a smaller page size than requested.
        raise JiraError("Zu viele Jira-Metadaten. Bitte das Projekt genauer eingrenzen.")

    def project_issue_types(self, project: str) -> list[dict]:
        return self._metadata_pages(f"/issue/createmeta/{self.check_project(project)}/issuetypes")

    def create_fields(self, project: str, issue_type_id: str) -> list[dict]:
        if not re.fullmatch(r"[0-9]+", issue_type_id or ""):
            raise ValueError("Tickettyp-ID muss numerisch sein (siehe Projekt-Tickettypen).")
        return self._metadata_pages(
            f"/issue/createmeta/{self.check_project(project)}/issuetypes/{issue_type_id}")

    def edit_fields(self, issue_key: str) -> dict:
        return self._call("GET", f"/issue/{self.check_key(issue_key)}/editmeta").get("fields", {})

    def priorities(self) -> list[dict]:
        return self._call("GET", "/priority")

    def link_types(self) -> list[dict]:
        return self._call("GET", "/issueLinkType").get("issueLinkTypes", [])

    # ------------------------------------------------------------ Helfer für Tools
    # Alle Helfer werfen JiraError mit verständlicher Meldung, wenn Jira einen Fehler meldet.

    def _call(self, method: str, path: str, ok: tuple = (200, 201, 204), **kwargs):
        try:
            r = self.request(method, path, **kwargs)
        except requests.RequestException as e:
            raise JiraError(f"Jira nicht erreichbar: {type(e).__name__}") from None
        if r.status_code not in ok:
            raise JiraError(f"Jira-Fehler (HTTP {r.status_code}): {r.text[:300]}")
        return r.json() if r.content else {}

    def search(self, jql: str, max_results: int = 20, fields: str = "summary,status,priority,assignee,updated",
               start_at: int = 0) -> dict:
        """Tickets per JQL. Liefert {"total": n, "issues": [...]} (Rohdaten von Jira)."""
        if start_at < 0:
            raise ValueError("start_at darf nicht negativ sein.")
        return self._call("GET", "/search", params={"jql": jql, "startAt": int(start_at), "maxResults": max(1, min(int(max_results), 100)),
                                                     "fields": fields})

    def issue(self, issue_key: str, fields: str = "*navigable") -> dict:
        return self._call("GET", f"/issue/{self.check_key(issue_key)}", params={"fields": fields})

    def create_issue(self, project: str, summary: str, issue_type: str = "Task", description: str = "",
                     **fields) -> str:
        """Legt ein Ticket an und liefert den neuen Key. Weitere Felder z. B. priority="High",
        components=["Bremse"], labels=["x"], assignee="user.name" oder customfield_10010=..."""
        data = {"project": {"key": self.check_project(project)},
                "summary": self.check_text(summary, "Titel", 255),
                "issuetype": {"name": self.check_text(issue_type, "Tickettyp", 255)}, "description": description}
        for name, value in fields.items():
            if name == "assignee" and isinstance(value, str):
                value = self.resolve_user(value)
            if name in ("priority", "assignee") and isinstance(value, str):
                value = {"name": value}
            elif name == "components":
                value = [{"name": c} for c in value]
            data[name] = value
        return self._call("POST", "/issue", json={"fields": data})["key"]

    def transitions(self, issue_key: str) -> list[dict]:
        """Mögliche Statuswechsel: [{"id": "21", "name": "In Arbeit", "to": "In Progress"}]."""
        data = self._call("GET", f"/issue/{self.check_key(issue_key)}/transitions",
                          params={"expand": "transitions.fields"})
        return [{"id": t["id"], "name": t["name"], "to": (t.get("to") or {}).get("name"), "fields": t.get("fields", {})}
                for t in data.get("transitions", [])]

    def transition(self, issue_key: str, name_or_id: str, comment: str = "", fields: dict | None = None) -> None:
        """Statuswechsel per Name der Transition oder Zielstatus (Groß/Klein egal) oder per ID."""
        wanted = str(name_or_id).strip().lower()
        options = self.transitions(issue_key)
        matches = [t for t in options if wanted in (t["id"], t["name"].lower(), (t["to"] or "").lower())]
        if not matches:
            raise JiraError(f"Statuswechsel '{name_or_id}' nicht möglich. Möglich: {[t['name'] for t in options]}")
        if len(matches) > 1:
            raise JiraError("Mehrere Statuswechsel passen. Bitte die konkrete Übergangs-ID angeben.")
        match = matches[0]
        body: dict = {"transition": {"id": match["id"]}}
        if fields:
            unknown = set(fields) - set(match["fields"])
            if unknown:
                raise ValueError(f"Felder im Statuswechsel nicht verfügbar: {sorted(unknown)}")
            body["fields"] = fields
        if comment:
            body["update"] = {"comment": [{"add": {"body": comment}}]}
        self._call("POST", f"/issue/{self.check_key(issue_key)}/transitions", json=body)

    def assign(self, issue_key: str, user_name: str) -> None:
        self._call("PUT", f"/issue/{self.check_key(issue_key)}/assignee", json={"name": self.resolve_user(user_name)})

    def comment(self, issue_key: str, text: str) -> None:
        self._call("POST", f"/issue/{self.check_key(issue_key)}/comment", json={"body": self.check_text(text, "Kommentar", 32767)})

    def comments(self, issue_key: str, max_results: int = 20) -> list[dict]:
        data = self._call("GET", f"/issue/{self.check_key(issue_key)}/comment",
                          params={"maxResults": max_results, "orderBy": "-created"})
        return [{"author": (c.get("author") or {}).get("displayName"), "created": c.get("created"),
                 "body": (c.get("body") or "")[:2000]} for c in data.get("comments", [])]

    def update_fields(self, issue_key: str, **fields) -> None:
        """Felder setzen, z. B. update_fields("ABC-1", summary="Neu", customfield_10010="x")."""
        self._call("PUT", f"/issue/{self.check_key(issue_key)}", json={"fields": fields})

    def set_priority(self, issue_key: str, priority: str) -> None:
        self.update_fields(issue_key, priority={"name": priority})

    def add_label(self, issue_key: str, label: str) -> None:
        self._call("PUT", f"/issue/{self.check_key(issue_key)}", json={"update": {"labels": [{"add": label}]}})

    def link(self, from_key: str, to_key: str, link_type: str = "Relates") -> None:
        """Verknüpft zwei Tickets, z. B. link("ABC-1", "ABC-2", "Blocks")."""
        self._call("POST", "/issueLink", json={"type": {"name": link_type},
                                               "outwardIssue": {"key": self.check_key(from_key)},
                                               "inwardIssue": {"key": self.check_key(to_key)}})

    def add_worklog(self, issue_key: str, time_spent: str, comment: str = "") -> None:
        """Arbeitszeit buchen, time_spent im Jira-Format, z. B. "1h 30m"."""
        if not re.fullmatch(r"(?:[1-9][0-9]*[wdhm])(?:\s+[1-9][0-9]*[wdhm])*", time_spent or ""):
            raise ValueError("Arbeitszeit z. B. als 1h 30m angeben.")
        self._call("POST", f"/issue/{self.check_key(issue_key)}/worklog",
                   json={"timeSpent": time_spent, "comment": comment})

    def find_users(self, query: str, max_results: int = 10) -> list[dict]:
        data = self._call("GET", "/user/search", params={"username": query, "maxResults": max_results})
        return [{"name": u.get("name"), "displayName": u.get("displayName")} for u in data]

    def projects(self) -> list[dict]:
        return [{"key": p.get("key"), "name": p.get("name")} for p in self._call("GET", "/project")]

    def fields(self) -> list[dict]:
        """Alle Felder inkl. Custom Fields: [{"id": "customfield_10010", "name": "Sprint"}]."""
        return [{"id": f.get("id"), "name": f.get("name")} for f in self._call("GET", "/field")]
