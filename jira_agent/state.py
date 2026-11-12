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
    created: float = field(default_factory=time.time)
    files: dict = field(default_factory=dict)          # vom Agenten erzeugte Dateien (Diagramme, Exporte)
    uploads: dict = field(default_factory=dict)        # vom Nutzer hochgeladene Dateien
    skills: dict | None = None                         # persönliche Skills (geladen aus dem Home-Ordner)

    def __repr__(self) -> str:
        return f"UserState(jira={self.jira_user is not None}, files={len(self.files)}, uploads={len(self.uploads)})"

    def expired(self, now: float) -> bool:
        return now - self.created > _CRED_TTL


_users: dict[str, UserState] = {}
_lock = threading.Lock()


def _get(email: str) -> UserState:
    """Sitzung des Nutzers. Verfällt spätestens credentials_ttl_hours nach dem Anlegen (nicht gleitend)."""
    now = time.time()
    for key in [k for k, s in _users.items() if s.expired(now)]:
        _users.pop(key)
    state = _users.get(email)
    if state is None:
        state = UserState()
        _users[email] = state
    return state


def user_state(email: str) -> UserState:
    with _lock:
        return _get(email)


def logout(email: str) -> None:
    with _lock:
        _users.pop(email, None)


def _store(email: str, kind: str, name: str, mime: str, data: bytes) -> str:
    """Legt eine Datei in state.files bzw. state.uploads ab (mit Ablaufzeit und Höchstzahl) und liefert die ID."""
    if len(data) > _MAX_FILE_BYTES:
        raise ValueError(f"Datei ist zu groß (max. {_MAX_FILE_BYTES // (1024 * 1024)} MB).")
    with _lock:
        files = getattr(_get(email), kind)
        now = time.time()
        for fid in [f for f, v in files.items() if now - v.created > _FILE_TTL]:
            files.pop(fid)
        while len(files) >= _MAX_FILES:
            files.pop(next(iter(files)))
        fid = secrets.token_urlsafe(16)
        files[fid] = StoredFile(name, mime, data)
    return fid


def _load(email: str, kind: str, fid: str) -> StoredFile | None:
    with _lock:
        state = _users.get(email)
        if not state or state.expired(time.time()):
            return None
        files = getattr(state, kind)
        f = files.get(fid)
        if f and time.time() - f.created > _FILE_TTL:
            files.pop(fid, None)
            return None
        return f


class FileSink:
    """Legt erzeugte Dateien für genau einen Nutzer ab und liefert die Download-URL."""

    def __init__(self, email: str):
        self.email = email

    def __repr__(self) -> str:
        return "FileSink()"

    def put(self, name: str, mime: str, data: bytes) -> str:
        return f"/jira/files/{_store(self.email, 'files', name, mime, data)}"


def get_file(email: str, fid: str) -> StoredFile | None:
    return _load(email, "files", fid)


class UploadSink:
    """Vom Nutzer hochgeladene Dateien (nur im Speicher, laufen nach files_ttl_minutes ab)."""

    def __init__(self, email: str):
        self.email = email

    def __repr__(self) -> str:
        return "UploadSink()"

    def put(self, name: str, mime: str, data: bytes) -> str:
        return _store(self.email, "uploads", name, mime, data)

    def get(self, fid: str) -> StoredFile | None:
        return _load(self.email, "uploads", fid)

    def list(self) -> list[dict]:
        with _lock:
            state = _users.get(self.email)
            items = list(state.uploads.items()) if state else []
        now = time.time()
        return [{"id": fid, "name": f.name, "mime": f.mime, "bytes": len(f.data)}
                for fid, f in items if now - f.created <= _FILE_TTL]

    def delete(self, fid: str) -> None:
        with _lock:
            state = _users.get(self.email)
            if state:
                state.uploads.pop(fid, None)
