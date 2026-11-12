"""Distinguish a completed transport from a successful application tool result."""
from pathlib import Path

_ANCHOR = '  const effectiveState: ToolState = (() => {\n'
_MARKER = '    // Jira Agent: reflect application errors and approval results in the badge.\n'
_RULES = _MARKER + """    if (state === 'output-available' && !isMcpApproval) {
      let result: any = output;
      if (typeof result === 'string') {
        try { result = JSON.parse(result); } catch { result = null; }
      }
      if (result && typeof result === 'object') {
        if (result.error || result.outcome === 'unverified' || result.status === 'RESULT_TOO_LARGE') return 'output-error';
        if (result.status === 'BESTAETIGUNG_NOETIG') return 'approval-requested';
        if (result.status === 'AKTION_LAEUFT') return 'input-available';
      }
    }
"""


def ensure_frontend_results(frontend: Path) -> None:
    file=frontend/'client/src/components/message.tsx'
    source=file.read_text(encoding='utf-8')
    if _MARKER in source:return
    if source.count(_ANCHOR)!=1:
        raise RuntimeError('Chat-Frontend geändert: Tool-Ergebnisstatus vor dem Build prüfen.')
    file.write_text(source.replace(_ANCHOR,_ANCHOR+_RULES,1),encoding='utf-8')
