from pathlib import Path

import pytest

from scripts.frontend_details import ensure_frontend_details


def renderer(tmp_path: Path, source: str) -> Path:
    file = tmp_path / 'client/src/components/message.tsx'
    file.parent.mkdir(parents=True)
    file.write_text(source)
    return file


def test_both_tool_renderers_start_closed_on_fresh_and_existing_frontends(tmp_path):
    file = renderer(tmp_path, '<McpTool defaultOpen={true}>approval controls</McpTool>\n'
                              '<Tool defaultOpen={true}>parameters and result</Tool>')
    ensure_frontend_details(tmp_path)
    patched = file.read_text()
    assert patched.count('defaultOpen={false}') == 2
    assert 'approval controls' in patched and 'parameters and result' in patched
    ensure_frontend_details(tmp_path)
    assert file.read_text() == patched


def test_unknown_renderer_fails_without_partially_changing_the_other(tmp_path):
    source = '<Tool defaultOpen={true}>result</Tool>\n<McpTool open={true}/>'
    file = renderer(tmp_path, source)
    with pytest.raises(RuntimeError, match='disclosure defaults'):
        ensure_frontend_details(tmp_path)
    assert file.read_text() == source
