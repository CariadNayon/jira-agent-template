"""Original annotated screenshots are linked to the relevant development steps."""
from pathlib import Path
from xml.etree import ElementTree

ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "jira_agent/static/guide.html").read_text(encoding="utf-8")
SECTION = HTML.split('<section class="part" id="ai-development">', 1)[1].split(
    '<section class="part" id="skills-guide">', 1
)[0]
IMAGES = {
    "ai_original_choose_folder.svg": "Choose your local folder",
    "ai_original_git_clone_terminal.svg": "Clone the repository in PowerShell",
    "ai_original_genie_develop.svg": "Open Genie Code with the project selected",
}


def test_missing_original_screenshots_are_linked():
    for filename, caption in IMAGES.items():
        assert f'/jira/static/img/{filename}' in SECTION
        assert caption in SECTION
    assert "Open the personal Databricks Git folder" in SECTION
    assert "/jira/static/img/ai_original_git_folder.svg" in SECTION
    assert "Original screenshot" in SECTION


def test_original_annotated_images_are_valid_svg_with_embedded_screenshots():
    ns = "{http://www.w3.org/2000/svg}"
    for filename in IMAGES:
        data = (ROOT / "jira_agent/static/img" / filename).read_text(encoding="utf-8")
        root = ElementTree.fromstring(data)
        assert root.tag == f"{ns}svg"
        assert any(
            el.attrib.get("href", "").startswith("data:image/webp;base64,")
            for el in root.iter(f"{ns}image")
        )
        assert "marker-end=" in data and "#ff2020" in data
