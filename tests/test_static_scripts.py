"""Syntax check for the browser code that is injected into the chat UI and the settings panel."""
import re
import shutil
import subprocess
from pathlib import Path

import pytest

STATIC = Path(__file__).resolve().parent.parent / 'jira_agent' / 'static'
NODE = shutil.which('node')

pytestmark = pytest.mark.skipif(NODE is None, reason='Node required to check JavaScript syntax')


def check(path: Path, source: str):
    target = path.parent / ('_syntax_' + path.stem + '.js')
    target.write_text(source, encoding='utf-8')
    try:
        result = subprocess.run([NODE, '--check', str(target)], capture_output=True, text=True, timeout=60)
    finally:
        target.unlink(missing_ok=True)
    assert result.returncode == 0, result.stderr


def test_ui_script_has_valid_syntax():
    path = STATIC / 'ui.js'
    check(path, path.read_text(encoding='utf-8'))


def test_inline_scripts_of_html_pages_have_valid_syntax(tmp_path):
    for name in ('settings.html', 'guide.html'):
        html = (STATIC / name).read_text(encoding='utf-8')
        for i, script in enumerate(re.findall(r'<script(?![^>]*\bsrc=)[^>]*>(.*?)</script>', html, re.S)):
            check(STATIC / f'{name}.{i}', script)
