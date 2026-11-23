"""Visual annotations in the AI development guide are committed and accessible."""
from html.parser import HTMLParser
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
GUIDE = ROOT / "jira_agent/static/guide.html"
FILES = (
    "ai_branch_selector.svg",
    "ai_branch_pull_create.svg",
    "ai_branch_name.svg",
    "ai_deploy_menu.svg",
    "ai_deploy_branch.svg",
    "ai_windows_terminal.svg",
)


class Images(HTMLParser):
    def __init__(self):
        super().__init__()
        self.sources = []
        self.buttons = 0

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "img":
            self.sources.append(a.get("src", ""))
        if tag == "button" and "screenshot" in a.get("class", "").split():
            self.buttons += 1


def test_ai_development_visuals_exist_and_have_arrows():
    html = GUIDE.read_text(encoding="utf-8")
    section = html.split('<section class="part" id="ai-development">', 1)[1].split(
        '<section class="part" id="skills-guide">', 1
    )[0]
    parser = Images()
    parser.feed(section)
    assert parser.buttons >= len(FILES)
    for name in FILES:
        assert f'/jira/static/img/{name}' in parser.sources
        svg = (ROOT / "jira_agent/static/img" / name).read_text(encoding="utf-8")
        assert svg.startswith('<svg ')
        assert 'stroke="#f43f35"' in svg
        assert 'marker-end:url(#arrow)' in svg
    assert "Click to enlarge" in section
    assert "UI illustration" in section
