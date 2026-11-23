"""The guide image route serves both preexisting PNGs and new SVG illustrations."""
import asyncio
from pathlib import Path
from xml.etree import ElementTree

import pytest
from fastapi import HTTPException

from jira_agent.web import guide_image


ROOT = Path(__file__).resolve().parents[1]
NAMES = (
    "ai_branch_selector.svg",
    "ai_branch_pull_create.svg",
    "ai_branch_name.svg",
    "ai_deploy_menu.svg",
    "ai_deploy_branch.svg",
    "ai_windows_terminal.svg",
)


@pytest.mark.parametrize("name", NAMES)
def test_svg_images_are_served_with_correct_mime(name):
    response = asyncio.run(guide_image(name))
    assert response.status_code == 200
    assert response.media_type == "image/svg+xml"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.body == (ROOT / "jira_agent/static/img" / name).read_bytes()
    assert ElementTree.fromstring(response.body).tag == "{http://www.w3.org/2000/svg}svg"


def test_existing_png_still_works():
    response = asyncio.run(guide_image("go_to_workspace.png"))
    assert response.media_type == "image/png"
    assert response.body.startswith(bytes([137, 80, 78, 71, 13, 10, 26, 10]))


@pytest.mark.parametrize("name", ["../web.py", "nope.svg", "web.html", "upper.SVG"])
def test_other_paths_are_rejected(name):
    with pytest.raises(HTTPException) as caught:
        asyncio.run(guide_image(name))
    assert caught.value.status_code == 404
