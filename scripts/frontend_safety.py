"""Disable automatic replay of agent requests after a stream/network error.

No chunk is not evidence of no side effect: Python may have written to Jira
before the first chunk reaches the browser. Apply before building on each start.
"""
from pathlib import Path

_MARKER = "// Jira Agent: contextual service errors; never replay an agent run."
_STREAM_ANCHOR = "    const result = streamText({\n"
_RETRY_MARKER = "      maxRetries: 0, // Jira Agent: retries require action reconciliation.\n"
_SIGNATURE = """export async function drainStreamToWriter(
  uiStream: ReadableStream,
  writer: UIMessageStreamWriter,
): Promise<{ failed: boolean; errorText?: string }> {"""
_SAFE_DRAIN = _SIGNATURE + """
  // Jira Agent: contextual service errors; never replay an agent run.
  const reader = uiStream.getReader();
  try {
    for (let chunk = await reader.read(); !chunk.done; chunk = await reader.read()) {
      if (chunk.value.type === 'error') {
        let message = chunk.value.errorText || 'The request failed.';
        // Older backends report only "Error code: 429". New backends include a safe
        // service explanation and Retry-After when the provider supplied it.
        if (/\\b429\\b/.test(message) && !message.startsWith('The AI model service ')) {
          message = 'The AI service reached a rate or capacity limit (429). '
            + 'Wait a moment before continuing. If this persists, ask an app administrator to check the model deployment quota.';
        }
        writer.write({ type: 'data-error', data:
          message
          + ' The agent was not restarted. '
          + 'If you already approved a Jira change, check its result before repeating that action.' });
        return { failed: false };
      }
      writer.write(chunk.value);
    }
  } catch (error) {
    writer.write({ type: 'data-error', data:
      'The connection was interrupted. The agent was not restarted. '
      + 'If you already approved a Jira change, it may still be running or may have completed. Check its result before repeating that action.' });
  } finally {
    reader.releaseLock();
  }
  return { failed: false };
}
"""


# Upgrade messages in already-patched local frontends as well as fresh downloads.
_LEGACY_MESSAGES = {'Die Anfrage ist fehlgeschlagen.': 'The request failed.', ' Es erfolgt keine automatische Wiederholung. ': ' No automatic retry will be made. ', 'Prüfe vor einem erneuten Versuch, ob eine Jira-Änderung bereits übernommen wurde.': 'Before retrying, check whether a Jira change was already applied.', 'Die Verbindung wurde unterbrochen. Der Agent wurde nicht erneut gestartet. ': 'The connection was interrupted. The agent was not restarted. ', 'Eine Jira-Aktion kann noch laufen oder bereits ausgeführt sein. Bitte zuerst prüfen.': 'A Jira action may still be running or may already have completed. Please check first.'}

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
        if "reader.releaseLock()" not in original or not (
            "receivedTextChunk" in original or "// Jira Agent: never replay an agent run after a transport failure." in original
        ):
            raise RuntimeError("Chat-Frontend geändert: Streaming-Ausweichpfad ist unbekannt.")
        source = source[:start] + _SAFE_DRAIN + source[end:]
    for before, after in _LEGACY_MESSAGES.items():
        source = source.replace(before, after)
    # Validate both files before writing either; repeated startup is safe.
    route.write_text(route_source, encoding="utf-8")
    fallback.write_text(source, encoding="utf-8")
