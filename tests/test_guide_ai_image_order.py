"""AI guide screenshots follow the workflow they illustrate."""
from pathlib import Path
from xml.etree import ElementTree

ROOT = Path(__file__).resolve().parents[1]
GUIDE = ROOT / "jira_agent/static/guide.html"

EXPECTED = [
    "ai_original_git_folder.svg",
    "ai_original_branch_main.png",
    "ai_original_pull_create.png",
    "ai_original_branch_name.png",
    "ai_original_deploy_menu.png",
    "ai_original_deploy_branch.png",
    "ai_original_genie_develop.svg",
    "ai_original_choose_folder.svg",
    "ai_original_terminal.png",
    "ai_original_git_clone_terminal.svg",
]


def test_ai_images_follow_actual_workflow():
    html = GUIDE.read_text(encoding="utf-8")
    section = html.split('<section class="part" id="ai-development">', 1)[1].split(
        '<section class="part" id="skills-guide">', 1
    )[0]
    positions = [section.index(f'src="/jira/static/img/{name}"') for name in EXPECTED]
    assert positions == sorted(positions)
    assert section.count('src="/jira/static/img/ai_original_git_folder.svg"') == 1
    assert section.count('src="/jira/static/img/ai_original_genie_develop.svg"') == 1

    create = section.index("<h3>Create your branch</h3>")
    pull = section.index("<h3>Open Git controls and pull</h3>")
    assert pull < create < positions[2]
    assert positions[1] < create
    assert positions[2] < positions[3]


def test_original_git_folder_illustration_has_embedded_photo():
    path = ROOT / "jira_agent/static/img/ai_original_git_folder.svg"
    content = path.read_text(encoding="utf-8")
    root = ElementTree.fromstring(content)
    assert root.tag == "{http://www.w3.org/2000/svg}svg"
    assert "data:image/webp;base64," in content
    assert "Open the Git folder" in content
