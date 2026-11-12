"""Disable automatic replay of agent requests after a stream/network error.

No chunk is not evidence of no side effect: Python may have written to Jira
before the first chunk reaches the browser. Apply before building on each start.
"""
from pathlib import Path

_MARKER = "// Jira Agent: never replay an agent run after a transport failure."
_STREAM_ANCHOR = "    const result = streamText({\n"
_RETRY_MARKER = "      maxRetries: 0, // Jira Agent: retries require action reconciliation.\n"
_SIGNATURE = """export async function drainStreamToWriter(
  uiStream: ReadableStream,
  writer: UIMessageStreamWriter,
): Promise<{ failed: boolean; errorText?: string }> {"""
_SAFE_DRAIN = _SIGNATURE + """
  // Jira Agent: never replay an agent run after a transport failure.
  const reader = uiStream.getReader();
  try {
    for (let chunk = await reader.read(); !chunk.done; chunk = await reader.read()) {
      if (chunk.value.type === 'error') {
        writer.write({ type: 'data-error', data:
          (chunk.value.errorText || 'Die Anfrage ist fehlgeschlagen.')
          + ' Es erfolgt keine automatische Wiederholung. '
          + 'Prüfe vor einem erneuten Versuch, ob eine Jira-Änderung bereits übernommen wurde.' });
        return { failed: false };
      }
      writer.write(chunk.value);
    }
  } catch (error) {
    writer.write({ type: 'data-error', data:
      'Die Verbindung wurde unterbrochen. Der Agent wurde nicht erneut gestartet. '
      + 'Eine Jira-Aktion kann noch laufen oder bereits ausgeführt sein. Bitte zuerst prüfen.' });
  } finally {
    reader.releaseLock();
  }
  return { failed: false };
}
"""


def ensure_frontend_safety(frontend: Path) -> None:
    route = frontend / "server/src/routes/chat.ts"
    fallback = frontend / "server/src/lib/stream-fallback.ts"
    route_source = route.read_text(encoding="utf-8")
    source = fallback.read_text(encoding="utf-8")
    if _RETRY_MARKER not in route_source:
        if route_source.count(_STREAM_ANCHOR) != 1:
            raise RuntimeError("Chat-Frontend geändert: streamText-Wiederholungen vor dem Build prüfen.")
        route_source = route_source.replace(_STREAM_ANCHOR, _STREAM_ANCHOR + _RETRY_MARKER, 1)
    if _MARKER not in source:
        if source.count(_SIGNATURE) != 1:
            raise RuntimeError("Chat-Frontend geändert: Streaming-Ausweichpfad vor dem Build prüfen.")
        start = source.index(_SIGNATURE)
        end = source.index("\n}\n", start) + 3
        original = source[start:end]
        if "reader.releaseLock()" not in original or "receivedTextChunk" not in original:
            raise RuntimeError("Chat-Frontend geändert: Streaming-Ausweichpfad ist unbekannt.")
        source = source[:start] + _SAFE_DRAIN + source[end:]
    # Validate both files before writing either; repeated startup is safe.
    route.write_text(route_source, encoding="utf-8")
    fallback.write_text(source, encoding="utf-8")
