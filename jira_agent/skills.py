"""Skills: wiederverwendbare Anleitungen, die Nutzer im Chat mit /name aufrufen.

Format (Markdown mit Kopfteil):

    ---
    name: wochenreport
    beschreibung: Erstellt einen Wochenbericht meiner Tickets
    ---
    1. Suche alle Tickets, die ich diese Woche bearbeitet habe …
    2. …

Quellen:
- Team-Skills: Dateien in skills/ im Repo (für alle Nutzer, kommen per Deploy)
- Persönliche Skills: im Zahnrad angelegt, gespeichert in /Users/<email>/.jira-agent/skills.json (mit dem
  Token des Nutzers, nur für ihn). "Für Team vorschlagen" lädt einen Skill als .md herunter.
"""
from __future__ import annotations

import io
import json
import re
from pathlib import Path

import yaml

from jira_agent.settings_store import settings_path

TEAM_DIR = Path(__file__).resolve().parent.parent / "skills"
NAME_RE = re.compile(r"[a-z0-9][a-z0-9-]{1,39}")
INVOKE_RE = re.compile(r"^\s*/([a-z0-9][a-z0-9-]{1,39})(?=\s|$)\s*(.*)", re.S)
MAX_DESCRIPTION = 200
MAX_INSTRUCTIONS = 8000
MAX_PERSONAL = 50


def check_skill(name: str, beschreibung: str, anleitung: str) -> dict:
    name = (name or "").strip().lower()
    if not NAME_RE.fullmatch(name):
        raise ValueError("Name: 2–40 Zeichen, nur Kleinbuchstaben, Ziffern und Bindestriche (z. B. wochenreport).")
    beschreibung = " ".join((beschreibung or "").split())
    if not beschreibung or len(beschreibung) > MAX_DESCRIPTION:
        raise ValueError(f"Beschreibung: 1–{MAX_DESCRIPTION} Zeichen.")
    anleitung = (anleitung or "").strip()
    if not anleitung or len(anleitung) > MAX_INSTRUCTIONS:
        raise ValueError(f"Anleitung: 1–{MAX_INSTRUCTIONS} Zeichen.")
    return {"name": name, "beschreibung": beschreibung, "anleitung": anleitung}


def parse_skill(text: str, fallback_name: str = "") -> dict:
    """Liest einen Skill im Markdown-Format (Kopfteil zwischen --- und ---, danach die Anleitung)."""
    m = re.match(r"\s*---\s*\n(.*?)\n---\s*\n?(.*)", text or "", re.S)
    if not m:
        raise ValueError("Kopfteil fehlt: Datei muss mit --- name: … beschreibung: … --- beginnen.")
    head = yaml.safe_load(m.group(1)) or {}
    return check_skill(str(head.get("name") or fallback_name),
                       str(head.get("beschreibung") or head.get("description") or ""), m.group(2))


def render_skill(skill: dict) -> str:
    head = yaml.safe_dump({"name": skill["name"], "beschreibung": skill["beschreibung"]},
                          allow_unicode=True, sort_keys=False)
    return f"---\n{head}---\n{skill['anleitung']}\n"


def team_skills(directory: Path = TEAM_DIR) -> dict[str, dict]:
    skills = {}
    for path in sorted(directory.glob("*.md")) if directory.exists() else []:
        try:
            s = parse_skill(path.read_text(encoding="utf-8"), path.stem)
        except ValueError:
            continue  # fehlerhafte Datei überspringen statt die App zu blockieren (Tests prüfen das Format)
        skills[s["name"]] = {**s, "quelle": "team"}
    return skills


def parse_invocation(text: str) -> tuple[str, str] | None:
    """'/wochenreport KW 46' -> ('wochenreport', 'KW 46')."""
    m = INVOKE_RE.match(text or "")
    return (m.group(1), m.group(2).strip()) if m else None


def skills_prompt(skills: dict[str, dict], last_user_text: str) -> str:
    """Abschnitt für den System-Prompt: verfügbare Skills und ggf. die Anleitung des aufgerufenen Skills."""
    lines = []
    if skills:
        lines.append("Skills (der Nutzer ruft sie mit /name auf; schlage passende vor):")
        lines += [f"- /{s['name']}: {s['beschreibung']}" for s in skills.values()]
    called = parse_invocation(last_user_text)
    if called:
        name, rest = called
        skill = skills.get(name)
        if skill:
            lines.append(f"\nDer Nutzer hat den Skill /{name} aufgerufen"
                         f"{' mit: ' + rest if rest else ''}. Folge genau dieser Anleitung:\n{skill['anleitung']}")
        else:
            lines.append(f"\nDer Nutzer hat /{name} geschrieben, diesen Skill gibt es nicht. "
                         "Sag das und nenne die verfügbaren Skills.")
    return "\n".join(lines)


class PersonalSkillStore:
    """Persönliche Skills im Home-Ordner des Nutzers (mit seinem Token)."""

    def __init__(self, user_client, email: str):
        self.w = user_client
        self.path = settings_path(email).rsplit("/", 1)[0] + "/skills.json"

    def load(self) -> dict[str, dict]:
        from databricks.sdk.errors import NotFound, ResourceDoesNotExist

        try:
            with self.w.workspace.download(self.path) as f:
                raw = json.loads(f.read().decode("utf-8"))
        except (NotFound, ResourceDoesNotExist):
            return {}
        skills = {}
        for item in raw if isinstance(raw, list) else []:
            try:
                s = check_skill(item.get("name"), item.get("beschreibung"), item.get("anleitung"))
            except (ValueError, AttributeError):
                continue
            skills[s["name"]] = {**s, "quelle": "persoenlich"}
        return skills

    def save(self, skills: dict[str, dict]) -> None:
        from databricks.sdk.service.workspace import ImportFormat

        data = [{k: s[k] for k in ("name", "beschreibung", "anleitung")} for s in skills.values()]
        self.w.workspace.mkdirs(self.path.rsplit("/", 1)[0])
        self.w.workspace.upload(self.path, io.BytesIO(json.dumps(data, ensure_ascii=False, indent=2).encode()),
                                format=ImportFormat.AUTO, overwrite=True)
