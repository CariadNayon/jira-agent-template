"""Speichert Einstellungen OHNE Geheimnisse im Home-Ordner des Nutzers (mit seinem eigenen Token).

Pfad: /Users/<email>/.jira-agent/settings.json
Nur die Felder in ALLOWED werden gespeichert – Keys und Tokens nie.
"""
from __future__ import annotations

import io
import json
import re

ALLOWED = {
    "agent_name": str,
    "rules": str,
    "selected_tables": list,
    "llm_provider": str,
    "azure_endpoint": str,
    "azure_deployment": str,
    "azure_api_version": str,
}
_EMAIL_RE = re.compile(r"[\w.+\-]+@[\w\-]+(\.[\w\-]+)+")
AGENT_NAME_MAX = 40


def sanitize(settings: dict) -> dict:
    out = {}
    for key, typ in ALLOWED.items():
        value = settings.get(key)
        if isinstance(value, typ):
            out[key] = [str(v) for v in value] if typ is list else value
    if "agent_name" in out:
        out["agent_name"] = " ".join(out["agent_name"].split())[:AGENT_NAME_MAX]
    return out


def settings_path(email: str) -> str:
    if not _EMAIL_RE.fullmatch(email or ""):
        raise ValueError("Ungültige Nutzerkennung.")
    return f"/Users/{email}/.jira-agent/settings.json"


class SettingsStore:
    def __init__(self, user_client, email: str):
        self.w = user_client
        self.path = settings_path(email)

    def load(self) -> dict:
        from databricks.sdk.errors import NotFound, ResourceDoesNotExist

        try:
            with self.w.workspace.download(self.path) as f:
                return sanitize(json.loads(f.read().decode("utf-8")))
        except (NotFound, ResourceDoesNotExist):
            return {}

    def save(self, settings: dict) -> None:
        from databricks.sdk.service.workspace import ImportFormat

        data = json.dumps(sanitize(settings), ensure_ascii=False, indent=2).encode("utf-8")
        self.w.workspace.mkdirs(self.path.rsplit("/", 1)[0])
        self.w.workspace.upload(self.path, io.BytesIO(data), format=ImportFormat.AUTO, overwrite=True)
