"""Schlanker Jira-REST-Client (Data Center, Personal Access Token). Der Token lebt nur in dieser Instanz."""
from __future__ import annotations

import re

import requests

KEY_RE = re.compile(r"[A-Z][A-Z0-9_]+-\d+")
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
