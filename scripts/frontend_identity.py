"""Keep Databricks' trusted user identity when the downloaded chat UI calls Python.

The upstream route forwards the OBO token but currently omits the email. Patch
its shared stream/fallback header object before building, including on restarts.
Never derive identity from the chat body or model-generated context.
"""
from pathlib import Path

_MARKER = "// Jira Agent: preserve gateway identity for stream and fallback."
_ANCHOR = "    const requestHeaders = {\n"
_HEADERS = """      // Jira Agent: preserve gateway identity for stream and fallback.
      ...(req.headers['x-forwarded-email']
        ? { 'x-forwarded-email': req.headers['x-forwarded-email'] as string }
        : {}),
"""


def ensure_frontend_identity(frontend: Path) -> None:
    route = frontend / "server/src/routes/chat.ts"
    source = route.read_text(encoding="utf-8")
    if _MARKER in source:
        return
    if source.count(_ANCHOR) != 1:
        raise RuntimeError("Chat-Frontend geändert: Nutzerweitergabe vor dem Build prüfen (requestHeaders fehlt).")
    route.write_text(source.replace(_ANCHOR, _ANCHOR + _HEADERS, 1), encoding="utf-8")
