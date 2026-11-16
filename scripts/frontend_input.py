"""Never send an empty chat message.

The upstream send button is disabled for empty input, but pressing Enter calls
form.requestSubmit(), which bypasses the button and the form handler sends the
empty text anyway. Apply before building on each start.
"""
from pathlib import Path

_MARKER = "// Jira Agent: Enter bypasses the disabled send button;"
_ANCHOR = "          onSubmit={(event) => {\n            event.preventDefault();\n"
_GUARD = ("            " + _MARKER + " never send empty text\n"
          "            // or while attachments are still uploading.\n"
          "            if (!input.trim() || uploadQueue.length > 0) return;\n")


def ensure_frontend_input(frontend: Path) -> None:
    file = frontend / 'client/src/components/multimodal-input.tsx'
    source = file.read_text(encoding='utf-8')
    if _MARKER in source:
        return
    if source.count(_ANCHOR) != 1:
        raise RuntimeError('Chat-Frontend geändert: Senden ohne Eingabe vor dem Build prüfen.')
    file.write_text(source.replace(_ANCHOR, _ANCHOR + _GUARD, 1), encoding='utf-8')
