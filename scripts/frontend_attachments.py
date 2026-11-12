"""Expose the actual React chat ID to the injected upload UI, including new chats at /."""
from pathlib import Path

_ROOTS = (
    '<div className="flex h-dvh min-w-0 flex-col bg-background">',
    '<div className="overscroll-behavior-contain flex h-dvh min-w-0 touch-pan-y flex-col bg-background">',
)


def ensure_frontend_attachments(frontend: Path) -> None:
    path = frontend / 'client/src/components/chat.tsx'
    source = path.read_text(encoding='utf-8')
    for original in _ROOTS:
        patched = original.replace('<div ', '<div data-jira-chat-id={id} ')
        if patched in source:
            continue
        if source.count(original) != 1:
            raise RuntimeError('Chat-Frontend geändert: Gesprächskennung für Anhänge vor dem Build prüfen.')
        source = source.replace(original, patched, 1)
    path.write_text(source, encoding='utf-8')
