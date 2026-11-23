"""The AI development guide keeps personal edits out of the shared main branch."""
from html.parser import HTMLParser
from pathlib import Path


class GuideParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.sections = []
        self.ids = set()
        self.images = []

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        if "id" in attributes:
            assert attributes["id"] not in self.ids, f"Duplicate guide id: {attributes['id']}"
            self.ids.add(attributes["id"])
        if tag == "img":
            self.images.append(attributes.get("src"))


def test_ai_guide_personal_branch_flow():
    html = (Path(__file__).resolve().parents[1] / "jira_agent/static/guide.html").read_text(encoding="utf-8")
    start = html.index('<section class="part" id="ai-development">')
    end = html.index('<section class="part" id="skills-guide">', start)
    section = html[start:end]
    assert "Create a personal branch in Databricks" in section
    assert "Deploy with another source" in section
    assert "Automatic deployment" in section
    assert "Genie Code" in section
    assert "VS Code + GitHub Copilot" in section
    assert "Baramundi Kiosk" in section
    assert "Open in Terminal" in section
    assert "https://git.hub.vwgroup.com/v8ee318/jira_agent_template.git" in section
    assert 'git clone https://git.hub.vwgroup.com/v8ee318/jira_agent_template.git' in section
    assert "git switch -c" in section
    assert "git push origin" in section
    assert "uv run pytest tests -q" in section
    assert 'version = "0.10.9+alex.1"' in section
    assert "not</b> an automatic Git-branch detector" in section
    assert "Never release personal suffixes on main" in section


def test_ai_guide_has_valid_unique_anchors_and_existing_sections():
    html = (Path(__file__).resolve().parents[1] / "jira_agent/static/guide.html").read_text(encoding="utf-8")
    parser = GuideParser()
    parser.feed(html)
    for anchor in ("ai-development", "ai-create-branch", "ai-deploy-branch",
                   "ai-choose-path", "ai-versioning", "ai-check-deployment",
                   "skills-guide"):
        assert anchor in parser.ids
