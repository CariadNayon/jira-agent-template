"""Speicher pro Nutzer – nur im Arbeitsspeicher dieser App-Instanz (App mit 1 Instanz/1 Worker betreiben).

Hier liegen Keys der Sitzung, der Schlüssel für Bestätigungscodes, die geladenen Einstellungen und
erzeugte Dateien. Nichts davon wird auf Platte geschrieben; Keys verfallen nach credentials_ttl_hours.
"""
from __future__ import annotations

import secrets
import threading
import time
from dataclasses import dataclass, field

from jira_agent import CFG

_CRED_TTL = float(CFG["session"]["credentials_ttl_hours"]) * 3600
_FILE_TTL = float(CFG["session"]["files_ttl_minutes"]) * 60
_MAX_FILES = 30
_MAX_FILE_BYTES = 20 * 1024 * 1024


@dataclass(repr=False)
class StoredFile:
    name: str
    mime: str
    data: bytes
    created: float = field(default_factory=time.time)


@dataclass(repr=False)
class UserState:
    creds: dict = field(default_factory=dict)          # jira_token, azure_key – nie speichern/loggen
    jira_user: str | None = None
    jira_display_name: str | None = None              # z. B. "Lenz, Nayon" – für den Standardnamen
    settings: dict | None = None
    secret: bytes = field(default_factory=lambda: secrets.token_bytes(32))
    touched: float = field(default_factory=time.time)
    files: dict = field(default_factory=dict)

    def __repr__(self) -> str:
        return f"UserState(jira={self.jira_user is not None}, files={len(self.files)})"


_users: dict[str, UserState] = {}
_lock = threading.Lock()


def _get(email: str) -> UserState:
    state = _users.get(email)
    if state is None or time.time() - state.touched > _CRED_TTL:
        state = UserState()
        _users[email] = state
    state.touched = time.time()
    return state


def user_state(email: str) -> UserState:
    with _lock:
        return _get(email)


def logout(email: str) -> None:
    with _lock:
        _users.pop(email, None)


class FileSink:
    """Legt erzeugte Dateien für genau einen Nutzer ab und liefert die Download-URL."""

    def __init__(self, email: str):
        self.email = email

    def __repr__(self) -> str:
        return "FileSink()"

    def put(self, name: str, mime: str, data: bytes) -> str:
        if len(data) > _MAX_FILE_BYTES:
            raise ValueError("Datei ist zu groß.")
        with _lock:
            files = _get(self.email).files
            now = time.time()
            for fid in [f for f, v in files.items() if now - v.created > _FILE_TTL]:
                files.pop(fid)
            while len(files) >= _MAX_FILES:
                files.pop(next(iter(files)))
            fid = secrets.token_urlsafe(16)
            files[fid] = StoredFile(name, mime, data)
        return f"/jira/files/{fid}"


def get_file(email: str, fid: str) -> StoredFile | None:
    with _lock:
        state = _users.get(email)
        if not state:
            return None
        f = state.files.get(fid)
        if f and time.time() - f.created > _FILE_TTL:
            state.files.pop(fid, None)
            return None
        return f
