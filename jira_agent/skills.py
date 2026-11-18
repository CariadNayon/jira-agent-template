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
  Token des Nutzers, nur für ihn). Teilen: "Publish to catalog" (docs/REGISTRY.md).
"""
from __future__ import annotations

import io
import json
import re
import copy
from functools import lru_cache
from pathlib import Path

import yaml

from jira_agent.settings_store import settings_path

TEAM_DIR = Path(__file__).resolve().parent.parent / "skills"
NAME_RE = re.compile(r"[a-z0-9][a-z0-9-]{1,39}")
LEGACY_TEAM_NAMES = {'datei-auswertung': 'file-analysis', 'ticket-entwurf': 'issue-draft', 'ticket-zusammenfassung': 'issue-summary', 'wochenreport': 'weekly-report'}
INVOKE_RE = re.compile(r"^\s*/([a-z0-9][a-z0-9-]{1,39})(?=\s|$)\s*(.*)", re.S)
MAX_DESCRIPTION = 200
MAX_INSTRUCTIONS = 8000
MAX_PERSONAL = 50


def check_skill(name: str, beschreibung: str, anleitung: str) -> dict:
    name = (name or "").strip().lower()
    if not NAME_RE.fullmatch(name):
        raise ValueError("Name: 2–40 characters, lowercase letters, digits and hyphens only (e.g. weekly-report).")
    beschreibung = " ".join((beschreibung or "").split())
    if not beschreibung or len(beschreibung) > MAX_DESCRIPTION:
        raise ValueError(f"Description: 1–{MAX_DESCRIPTION} characters.")
    anleitung = (anleitung or "").strip()
    if not anleitung or len(anleitung) > MAX_INSTRUCTIONS:
        raise ValueError(f"Instructions: 1–{MAX_INSTRUCTIONS} characters.")
    return {"name": name, "beschreibung": beschreibung, "anleitung": anleitung}


def parse_skill(text: str, fallback_name: str = "") -> dict:
    """Liest einen Skill im Markdown-Format (Kopfteil zwischen --- und ---, danach die Anleitung)."""
    m = re.match(r"\s*---\s*\n(.*?)\n---\s*\n?(.*)", text or "", re.S)
    if not m:
        raise ValueError("Missing header: the file must start with --- name: … description: … ---.")
    head = yaml.safe_load(m.group(1)) or {}
    return check_skill(str(head.get("name") or fallback_name),
                       str(head.get("beschreibung") or head.get("description") or ""), m.group(2))


def render_skill(skill: dict) -> str:
    head = yaml.safe_dump({"name": skill["name"], "description": skill["beschreibung"]},
                          allow_unicode=True, sort_keys=False)
    return f"---\n{head}---\n{skill['anleitung']}\n"


@lru_cache(maxsize=128)
def _parsed_team_file(path: str, modified_ns: int, size: int) -> dict:
    file = Path(path)
    return parse_skill(file.read_text(encoding='utf-8'), file.stem)


def team_skills(directory: Path = TEAM_DIR) -> dict[str, dict]:
    skills = {}
    for path in sorted(directory.glob("*.md")) if directory.exists() else []:
        try:
            stat = path.stat()
            s = copy.deepcopy(_parsed_team_file(str(path.resolve()), stat.st_mtime_ns, stat.st_size))
        except ValueError:
            continue  # fehlerhafte Datei überspringen statt die App zu blockieren (Tests prüfen das Format)
        skills[s["name"]] = {**s, "quelle": "team"}
    return skills


def parse_invocation(text: str) -> tuple[str, str] | None:
    """'/wochenreport KW 46' -> ('wochenreport', 'KW 46'). Nur am Anfang der Nachricht."""
    m = INVOKE_RE.match(text or "")
    return (m.group(1), m.group(2).strip()) if m else None


# Aufruf mitten in einer Nachricht: /name nach Leerzeichen, Zeilenanfang oder "(" und vor Leerzeichen, Satzzeichen
# oder Ende. Pfade (/tmp/x), URLs und a/b werden dadurch nicht erfasst.
_TOKEN_RE = re.compile(r"(?<![^\s(])/([a-z0-9][a-z0-9-]{1,39})(?=[\s.,;:!?)]|$)")
MAX_INVOKED = 3


def is_known_skill(name: str, skills: dict | None) -> bool:
    return bool(skills) and (name in skills or LEGACY_TEAM_NAMES.get(name) in skills)


def find_invocations(text: str, skills: dict | None = None) -> list[tuple[str, str, bool]]:
    """Skills, die eine Nutzernachricht aufruft: [(name, rest, am_anfang)], höchstens MAX_INVOKED.

    Am Anfang gilt jeder Name (ein unbekannter wird erklärt). Mitten im Text zählt nur ein bekannter Skill oder
    /clear-skill, damit Pfade und Wörter wie "/tmp" keine Fehlalarme auslösen. Ohne `skills` nur der Anfang.
    """
    text = text or ""
    found: list[tuple[str, str, bool]] = []
    seen: set[str] = set()
    lead = parse_invocation(text)
    if lead:
        found.append((lead[0], lead[1], True))
        seen.add(lead[0])
    if skills is not None:
        for m in _TOKEN_RE.finditer(text):
            name = m.group(1)
            if name not in seen and (name == "clear-skill" or is_known_skill(name, skills)):
                found.append((name, "", False))
                seen.add(name)
    return found[:MAX_INVOKED]


def active_skill_invocation(messages: list[dict], skills: dict | None = None) -> str | None:
    """Keep an explicit skill active across user follow-ups, using only this chat's user messages."""
    latest_user = True
    for message in reversed(messages):
        if message.get('role') != 'user':
            continue
        content = message.get('content', '')
        if isinstance(content, list):
            content = ' '.join(part['text'] for part in content
                               if isinstance(part, dict) and isinstance(part.get('text'), str))
        called = find_invocations(content, skills) if isinstance(content, str) else []
        if called:
            if any(name == 'clear-skill' for name, _, _ in called):
                return ''
            if skills is not None and not any(is_known_skill(name, skills) for name, _, _ in called):
                return content if latest_user else ''
            return content
        latest_user = False
    return None


def skills_prompt(skills: dict[str, dict], last_user_text: str) -> str:
    """Abschnitt für den System-Prompt: verfügbare Skills und ggf. die Anleitung der aufgerufenen Skills."""
    lines = []
    if skills:
        lines.append("Skills (the user invokes them with /name, at the start or anywhere inside a message; suggest relevant ones):")
        lines.append("An explicitly selected skill stays active for related follow-ups. The current user's corrections or rejection take precedence. /clear-skill ends it; another /name selects a different skill.")
        lines += [f"- /{s['name']}: {s['beschreibung']}" for s in skills.values()]
    for name, rest, leading in find_invocations(last_user_text, skills):
        if name == "clear-skill":
            continue
        skill = skills.get(name) or skills.get(LEGACY_TEAM_NAMES.get(name, ""))
        if skill and leading:
            lines.append(f"\nThe user invoked the skill /{name}"
                         f"{' with: ' + rest if rest else ''}. Follow these instructions exactly:\n{skill['anleitung']}")
        elif skill:
            lines.append(f"\nThe user invoked the skill /{name} inside their message. Follow these instructions "
                         f"exactly while handling the user's whole request as written:\n{skill['anleitung']}")
        else:
            lines.append(f"\nThe user entered /{name}, but this skill does not exist. "
                         "Explain this and list the available skills.")
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
