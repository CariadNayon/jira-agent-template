import pytest

from scripts.frontend_input import _ANCHOR, ensure_frontend_input


def component(tmp_path, source):
    file = tmp_path / 'client/src/components/multimodal-input.tsx'
    file.parent.mkdir(parents=True)
    file.write_text(source)
    return file


def test_enter_cannot_send_empty_text_and_patch_is_idempotent(tmp_path):
    file = component(tmp_path, 'before\n' + _ANCHOR + '            submitForm();\nafter')
    ensure_frontend_input(tmp_path)
    patched = file.read_text()
    guard = patched.index('!input.trim()')
    assert patched.index('event.preventDefault()') < guard < patched.index('submitForm()')
    assert 'uploadQueue.length > 0' in patched
    ensure_frontend_input(tmp_path)
    assert file.read_text() == patched


def test_unknown_frontend_fails_loudly(tmp_path):
    file = component(tmp_path, 'unknown layout')
    with pytest.raises(RuntimeError, match='Senden ohne Eingabe'):
        ensure_frontend_input(tmp_path)
    assert file.read_text() == 'unknown layout'
