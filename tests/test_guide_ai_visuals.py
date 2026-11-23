"""Original annotated screenshots appear in the AI guide with valid PNGs."""
from html.parser import HTMLParser
from pathlib import Path
from struct import unpack

ROOT = Path(__file__).resolve().parents[1]
GUIDE = ROOT / "jira_agent/static/guide.html"
FILES = (
    "ai_original_branch_main.png",
    "ai_original_pull_create.png",
    "ai_original_branch_name.png",
    "ai_original_deploy_menu.png",
    "ai_original_deploy_branch.png",
    "ai_original_terminal.png",
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

def test_ai_guide_uses_original_screenshots():
    html = GUIDE.read_text(encoding="utf-8")
    section = html.split('<section class="part" id="ai-development">', 1)[1].split(
        '<section class="part" id="skills-guide">', 1
    )[0]
    parser = Images()
    parser.feed(section)
    assert parser.buttons >= len(FILES)
    for name in FILES:
        assert f'/jira/static/img/{name}' in parser.sources
        data = (ROOT / "jira_agent/static/img" / name).read_bytes()
        assert data.startswith(bytes([137, 80, 78, 71, 13, 10, 26, 10]))
        width, height = unpack(">II", data[16:24])
        assert width >= 300 and height >= 140
        assert len(data) > 2000
    assert "Original screenshot (cropped)" in section
    assert "Red arrows mark the action" in section
    for old_name in ("ai_branch_selector.svg", "ai_branch_pull_create.svg", "ai_branch_name.svg", "ai_deploy_menu.svg", "ai_deploy_branch.svg", "ai_windows_terminal.svg"):
        assert old_name not in section
