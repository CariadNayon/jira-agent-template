import pytest

from scripts.frontend_markdown import _COMPONENT_ANCHOR, _IMPORT_ANCHOR, ensure_frontend_markdown

RESPONSE = ("import { Streamdown } from 'streamdown';\n<Streamdown components={{\n"
            "          a: DatabricksMessageCitationStreamdownIntegration,\n}} />\n")


def response(tmp_path, source=RESPONSE):
    file = tmp_path / 'client/src/components/elements/response.tsx'
    file.parent.mkdir(parents=True)
    file.write_text(source)
    return file


def test_code_and_mermaid_are_rendered_without_lazy_chunks_and_patch_is_idempotent(tmp_path):
    file = response(tmp_path)
    ensure_frontend_markdown(tmp_path)
    patched = file.read_text()
    assert "import { MarkdownCode } from './markdown-code';" in patched
    assert 'code: MarkdownCode,' in patched
    component = (file.parent / 'markdown-code.tsx').read_text()
    assert "securityLevel: 'strict'" in component and "import('mermaid')" in component
    ensure_frontend_markdown(tmp_path)
    assert file.read_text() == patched and patched.count('MarkdownCode') == 2


def test_unknown_frontend_fails_loudly(tmp_path):
    file = response(tmp_path, 'unknown layout')
    with pytest.raises(RuntimeError, match='Markdown-Darstellung'):
        ensure_frontend_markdown(tmp_path)
    assert file.read_text() == 'unknown layout'
    assert _IMPORT_ANCHOR in RESPONSE and _COMPONENT_ANCHOR in RESPONSE
