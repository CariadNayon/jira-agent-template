"""Tests für Skills (/name), Datei-Upload und die zugehörigen Endpunkte."""
import io
import re

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from jira_agent.skills import (TEAM_DIR, active_skill_invocation, check_skill, find_invocations, parse_invocation,
                               parse_skill, render_skill, skills_prompt, team_skills)
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
    with pytest.raises(ValueError, match="Missing header"):
        parse_skill("nur Text")


def test_invocation_activates_skill_in_prompt():
    skills = {"wochenreport": {"name": "wochenreport", "beschreibung": "Bericht", "anleitung": "SCHRITTE-XYZ"}}
    assert parse_invocation("/wochenreport KW 46") == ("wochenreport", "KW 46")
    assert parse_invocation("bitte /wochenreport") is None      # parse_invocation kennt nur den Nachrichtenanfang
    assert parse_invocation("/pfad/zu/datei") is None

    prompt = skills_prompt(skills, "/wochenreport KW 46")
    assert "- /wochenreport: Bericht" in prompt and "SCHRITTE-XYZ" in prompt and "KW 46" in prompt
    assert "SCHRITTE-XYZ" not in skills_prompt(skills, "Hallo")
    assert "does not exist" in skills_prompt(skills, "/unbekannt")


SKILLS = {
    "triage": {"name": "triage", "beschreibung": "Sortiert", "anleitung": "TRIAGE-STEPS"},
    "weekly-report": {"name": "weekly-report", "beschreibung": "Bericht", "anleitung": "REPORT-STEPS"},
}


@pytest.mark.parametrize("text", [
    "Bitte mach das mit /triage für ABC-1",
    "Mach das und dann /triage.",
    "Kannst du (/triage) nutzen?",
    "erste Zeile\n/triage\nzweite Zeile",
    "Am Ende /triage",
])
def test_skill_can_be_invoked_in_the_middle_of_a_message(text):
    assert [n for n, _, _ in find_invocations(text, SKILLS)] == ["triage"]
    prompt = skills_prompt(SKILLS, text)
    assert "TRIAGE-STEPS" in prompt and "REPORT-STEPS" not in prompt
    assert "inside their message" in prompt and "does not exist" not in prompt


@pytest.mark.parametrize("text", [
    "Öffne /tmp und lies /etc/hosts",
    "Siehe https://example.com/triage",
    "pfad/triage und and/or triage/",
    "Der Ordner `/triage` und a/triage",
    "Ein /unbekannter-skill mitten im Satz",
    "triage ohne Schrägstrich",
])
def test_paths_urls_and_unknown_names_in_the_middle_are_not_skill_calls(text):
    assert find_invocations(text, SKILLS) == []
    assert "TRIAGE-STEPS" not in skills_prompt(SKILLS, text) and "does not exist" not in skills_prompt(SKILLS, text)


def test_leading_invocation_keeps_its_behaviour_and_mixes_with_later_ones():
    assert find_invocations("/triage ABC-1", SKILLS) == [("triage", "ABC-1", True)]
    assert find_invocations("/unbekannt", SKILLS) == [("unbekannt", "", True)]         # unknown: still explained
    both = find_invocations("/triage erst, danach /weekly-report", SKILLS)
    assert both == [("triage", "erst, danach /weekly-report", True), ("weekly-report", "", False)]
    prompt = skills_prompt(SKILLS, "/triage erst, danach /weekly-report")
    assert "TRIAGE-STEPS" in prompt and "REPORT-STEPS" in prompt
    assert find_invocations("/triage und /triage nochmal /triage", SKILLS) == [("triage", "und /triage nochmal /triage", True)]
    many = {f"skill-{i}": {"name": f"skill-{i}", "beschreibung": "x", "anleitung": "y"} for i in range(6)}
    assert len(find_invocations("a /skill-1 b /skill-2 c /skill-3 d /skill-4 e /skill-5", many)) == 3


def test_legacy_team_names_and_catalog_skills_work_in_the_middle():
    legacy = {"weekly-report": SKILLS["weekly-report"]}
    assert "REPORT-STEPS" in skills_prompt(legacy, "mach bitte /wochenreport für KW 46")
    assert find_invocations("nur /triage", None) == []          # ohne Skill-Liste zählt nur der Anfang


def test_mid_message_skill_stays_active_and_can_be_cleared():
    chat = [{"role": "user", "content": "Bitte /triage für ABC-1"},
            {"role": "assistant", "content": "Welches Projekt?"},
            {"role": "user", "content": "ABC"}]
    kept = active_skill_invocation(chat, SKILLS)
    assert kept == "Bitte /triage für ABC-1" and "TRIAGE-STEPS" in skills_prompt(SKILLS, kept)
    assert active_skill_invocation([*chat, {"role": "user", "content": "danke, /clear-skill"}], SKILLS) == ""
    assert active_skill_invocation([{"role": "user", "content": "ein /unbekannter text"}], SKILLS) is None


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


def test_upload_limit_applies_to_chunked_bodies_without_content_length(client):
    def chunks():
        for _ in range(21):
            yield b"x" * (1024 * 1024)
    r = client.post("/jira/api/upload?name=big.csv", content=chunks(), headers={"content-type": "text/csv"})
    assert r.status_code == 413
    assert "big.csv" not in [u["name"] for u in client.get("/jira/api/uploads").json()]


def test_excel_zip_bomb_is_rejected_before_reading(monkeypatch):
    import io
    import zipfile

    import jira_agent.table_data as table_data
    from jira_agent.tools.upload_tools import read_excel

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("xl/big.xml", b"0" * (2 * 1024 * 1024))
    monkeypatch.setattr(table_data, "_MAX_XLSX_BYTES", 1024 * 1024)
    with pytest.raises(ValueError, match="too large"):
        read_excel(buffer.getvalue(), 10)
    with pytest.raises(ValueError, match="damaged"):
        read_excel(b"not a zip", 10)


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
