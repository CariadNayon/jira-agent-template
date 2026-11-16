"""Start every tool disclosure closed; React retains the user's manual choice."""
from pathlib import Path


def ensure_frontend_details(frontend: Path) -> None:
    file = frontend / 'client/src/components/message.tsx'
    source = file.read_text(encoding='utf-8')
    # Check both renderers before writing; support fresh and already-patched frontends.
    for component in ('Tool', 'McpTool'):
        opened = f'<{component} defaultOpen={{true}}>'
        closed = f'<{component} defaultOpen={{false}}>'
        if source.count(opened) + source.count(closed) != 1:
            raise RuntimeError('Chat frontend changed: check tool disclosure defaults before building.')
        source = source.replace(opened, closed)
    file.write_text(source, encoding='utf-8')
