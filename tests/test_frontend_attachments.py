import pytest

from scripts.frontend_attachments import _ROOTS, ensure_frontend_attachments


def test_new_and_existing_chat_expose_real_id_and_patch_is_idempotent(tmp_path):
    file=tmp_path/'client/src/components/chat.tsx'
    file.parent.mkdir(parents=True)
    file.write_text('\n'.join(_ROOTS))
    ensure_frontend_attachments(tmp_path)
    first=file.read_text()
    assert first.count('data-jira-chat-id={id}') == 2
    ensure_frontend_attachments(tmp_path)
    assert file.read_text() == first


def test_unknown_frontend_does_not_silently_lose_chat_id(tmp_path):
    file=tmp_path/'client/src/components/chat.tsx'
    file.parent.mkdir(parents=True)
    file.write_text('unknown layout')
    with pytest.raises(RuntimeError,match='Gesprächskennung'):
        ensure_frontend_attachments(tmp_path)
    assert file.read_text() == 'unknown layout'
