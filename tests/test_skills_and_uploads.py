"""Tests für Skills (/name), Datei-Upload und die zugehörigen Endpunkte."""
import io
import re

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from jira_agent.skills import TEAM_DIR, check_skill, parse_invocation, parse_skill, render_skill, skills_prompt, team_skills
from jira_agent.state import UploadSink
from jira_agent.testing import run_tool
from jira_agent.tools import load_tools

_TOOL_WORD = re.compile(r"\b(jira_\w+|run_readonly_sql|describe_table|create_chart|export_file|\w+_uploaded_file\w*)\b")


def test_team_skills_are_valid_and_use_existing_tools():
    files = sorted(TEAM_DIR.glob("*.md"))
    assert files, "skills/ sollte Beispiel-Skills enthalten"
    tools = load_tools()
    for path in files:
        skill = parse_skill(path.read_text(encoding="utf-8"))  # wirft bei falschem Format
        assert skill["name"] == path.stem, f"{path.name}: Dateiname muss <name>.md sein"
        unknown = set(_TOOL_WORD.findall(skill["anleitung"])) - set(tools)
        assert not unknown, f"{path.name}: unbekannte Tools {unknown}"
    assert set(team_skills()) == {p.stem for p in files}


def test_skill_format_roundtrip_and_validation():
    skill = check_skill("Mein-Report", "  Kurz   und knapp ", "1. Mach was")
    assert skill == {"name": "mein-report", "beschreibung": "Kurz und knapp", "anleitung": "1. Mach was"}
    assert parse_skill(render_skill(skill)) == skill
    for bad in ("a", "mit leerzeichen", "ümlaut", "x" * 41, "-start"):
        with pytest.raises(ValueError):
            check_skill(bad, "b", "a")
    with pytest.raises(ValueError, match="Kopfteil"):
        parse_skill("nur Text")


def test_invocation_activates_skill_in_prompt():
    skills = {"wochenreport": {"name": "wochenreport", "beschreibung": "Bericht", "anleitung": "SCHRITTE-XYZ"}}
    assert parse_invocation("/wochenreport KW 46") == ("wochenreport", "KW 46")
    assert parse_invocation("bitte /wochenreport") is None
    assert parse_invocation("/pfad/zu/datei") is None

    prompt = skills_prompt(skills, "/wochenreport KW 46")
    assert "- /wochenreport: Bericht" in prompt and "SCHRITTE-XYZ" in prompt and "KW 46" in prompt
    assert "SCHRITTE-XYZ" not in skills_prompt(skills, "Hallo")
    assert "gibt es nicht" in skills_prompt(skills, "/unbekannt")


def test_read_uploaded_files():
    from openpyxl import Workbook

    sink = UploadSink("upload-test@example.com")
    csv_id = sink.put("daten.csv", "text/csv", "Name;Anzahl\nBremse;3\nLaden;5\n".encode("utf-8-sig"))
    wb = Workbook()
    wb.active.append(["Ticket", "Tage"])
    wb.active.append(["ABC-1", 4])
    buf = io.BytesIO()
    wb.save(buf)
    xlsx_id = sink.put("liste.xlsx", "application/octet-stream", buf.getvalue())
    txt_id = sink.put("notiz.md", "text/markdown", "# Hallo\nText".encode())
    img_id = sink.put("bild.png", "image/png", b"\x89PNG")

    csv_res = run_tool("read_uploaded_file", uploads=sink, file_id=csv_id)
    assert csv_res["columns"] == ["Name", "Anzahl"] and csv_res["rows"] == [["Bremse", "3"], ["Laden", "5"]]
    xlsx_res = run_tool("read_uploaded_file", uploads=sink, file_id=xlsx_id)
    assert xlsx_res["blaetter"]["Sheet"]["rows"] == [["ABC-1", 4]]
    assert run_tool("read_uploaded_file", uploads=sink, file_id=txt_id)["text"].startswith("# Hallo")
    assert run_tool("read_uploaded_file", uploads=sink, file_id=img_id)["error"] == "ValueError"
    assert run_tool("read_uploaded_file", uploads=sink, file_id="gibt-es-nicht")["error"] == "ValueError"
    assert {f["name"] for f in run_tool("list_uploaded_files", uploads=sink)["dateien"]} >= {"daten.csv", "liste.xlsx"}


@pytest.fixture()
def client(monkeypatch):
    import jira_agent.runtime as runtime
    import jira_agent.web as web

    stored = {}

    class FakeStore:
        def __init__(self, w, email):
            pass

        def load(self):
            return dict(stored)

        def save(self, skills):
            stored.clear()
            stored.update(skills)

    monkeypatch.setattr(web, "user_client", lambda token: object())
    monkeypatch.setattr(runtime, "user_client", lambda token: object())
    monkeypatch.setattr(web, "PersonalSkillStore", FakeStore)
    monkeypatch.setattr(runtime, "PersonalSkillStore", FakeStore)
    app = FastAPI()
    web.install(app)
    c = TestClient(app, headers={"x-forwarded-email": "web-test@example.com", "x-forwarded-access-token": "t"})
    c.stored = stored
    return c


def test_upload_endpoint(client):
    r = client.post("/jira/api/upload?name=../../böse name.csv", content=b"a;b\n1;2\n",
                    headers={"content-type": "text/csv"})
    assert r.status_code == 200 and r.json()["name"] == "böse name.csv"
    assert [u["name"] for u in client.get("/jira/api/uploads").json()] == ["böse name.csv"]
    assert client.post("/jira/api/upload?name=leer.txt", content=b"").status_code == 400
    assert client.post("/jira/api/upload?name=x.csv", content=b"x", headers={"x-forwarded-email": ""}).status_code == 401


def test_skill_endpoints(client):
    assert client.put("/jira/api/skills/triage", json={"beschreibung": "x", "anleitung": "y"}).status_code == 400
    r = client.put("/jira/api/skills/mein-skill", json={"beschreibung": "Meins", "anleitung": "1. Tu was"})
    assert r.status_code == 200 and "mein-skill" in client.stored

    listed = {s["name"]: s["quelle"] for s in client.get("/jira/api/skills").json()}
    assert listed["mein-skill"] == "persoenlich" and listed["triage"] == "team"
    md = client.get("/jira/api/skills/mein-skill/download")
    assert md.status_code == 200 and parse_skill(md.text)["anleitung"] == "1. Tu was"
    assert client.delete("/jira/api/skills/triage").status_code == 404
    assert client.delete("/jira/api/skills/mein-skill").status_code == 200 and not client.stored


def test_guide_images_only_from_img_folder(client):
    assert client.get("/jira/static/img/go_to_workspace.png").status_code == 200
    assert client.get("/jira/static/img/..%2Fui.js").status_code == 404
    assert client.get("/jira/static/img/gibt_es_nicht.png").status_code == 404
