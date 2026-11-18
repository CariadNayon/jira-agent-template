"""Debug log of a chat, kept in memory for the signed-in user and downloadable as a text file.

What is recorded per request: the system prompt the model got (including an invoked skill), the user's text, every
tool call with its arguments and result, the assistant answer, errors (for example a model 429) and the timing
counters. It lives only in this app instance's memory, next to the user's session: it expires with the session, is lost
on restart and can only be read by its owner. Known secrets (the user's keys and tokens) and token-like text are masked
and image data is omitted, but ticket or table content appears as it was; the file header says so.

Recording must never break a chat request, so every public function swallows its own errors.
"""
from __future__ import annotations

import json
import logging
import os
import re
import threading
import time
from datetime import datetime, timezone

from jira_agent import __version__
from jira_agent.state import user_state

_log = logging.getLogger("jira_agent.chatlog")

CHAT_ID_RE = re.compile(r"[A-Za-z0-9_-]{1,128}")
NO_CHAT = "no-conversation-id"
MAX_CHATS = 10                  # chats kept per user; the least recently used one is dropped first
MAX_CHARS_PER_CHAT = 1_500_000  # oldest requests of a chat are dropped beyond this
MAX_FIELD_CHARS = 20_000        # one prompt, tool argument or tool result is cut here
_lock = threading.Lock()

_PATTERNS = [
    (re.compile(r"(?i)\b(bearer|basic)\s+[A-Za-z0-9._~+/=-]{12,}"), r"\1 [redacted]"),
    (re.compile(r"(?i)((?:authorization|api[_-]?key|access[_-]?token|jira[_-]?token|azure[_-]?key|client[_-]?secret"
                r"|secret|password)[\"']?\s*[:=]\s*[\"']?)[^\s\"',}]{6,}"), r"\1[redacted]"),
    (re.compile(r"data:[a-z0-9.+/-]+;base64,[A-Za-z0-9+/=_-]{40,}", re.I), "[binary data omitted]"),
]


def redact(text: object, secrets: list[str] | None = None, limit: int = MAX_FIELD_CHARS) -> str:
    """Mask known secrets and token-like text, drop inline image data and cut very long values."""
    text = text if isinstance(text, str) else json.dumps(text, ensure_ascii=False, default=str)
    for secret in secrets or []:
        text = text.replace(secret, "[redacted]")
    for pattern, replacement in _PATTERNS:
        text = pattern.sub(replacement, text)
    if len(text) > limit:
        text = text[:limit] + f"\n[... cut: {len(text) - limit} more characters]"
    return text


def _utc(ts: float | None = None) -> str:
    return datetime.fromtimestamp(ts if ts is not None else time.time(), timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def format_item(item: object, secrets: list[str]) -> str:
    """One run item (as a Responses-API dict) as a readable log line."""
    if not isinstance(item, dict):
        return "[item] " + redact(str(item), secrets)
    kind = item.get("type")
    if kind == "function_call":
        return f"[tool call] {item.get('name')}  args: {redact(item.get('arguments', ''), secrets)}"
    if kind == "function_call_output":
        return f"[tool result] {redact(item.get('output', ''), secrets)}"
    if kind == "reasoning":
        return "[reasoning] (not recorded)"
    if kind == "message" or "role" in item:
        content = item.get("content", "")
        if isinstance(content, list):
            content = "\n".join(p.get("text", "") for p in content if isinstance(p, dict) and p.get("text"))
        return f"[{item.get('role', 'message')}] {redact(content, secrets)}"
    return f"[{kind or 'item'}] {redact(item, secrets)}"


class Recorder:
    """Collects one request and stores it as a block of the chat's log when the request ends."""

    def __init__(self, state, email: str, chat: str, user_text: str, history_items: int, token: str | None):
        self.state, self.email, self.chat = state, email, chat
        self.user_text, self.history_items, self.token = user_text, history_items, token
        self.started = time.time()
        self.prompt = ""
        self.model = ""
        self.tools: list[str] = []

    def set_agent(self, agent) -> None:
        try:
            self.prompt = str(getattr(agent, "instructions", "") or "")
            model = getattr(agent, "model", None)
            self.model = str(getattr(model, "model", None) or type(model).__name__)
            self.tools = [str(getattr(t, "name", "")) for t in getattr(agent, "tools", [])]
        except Exception:
            _log.warning("Chat log: could not read the agent", exc_info=True)

    def _secrets(self) -> list[str]:
        values = [v for v in self.state.creds.values() if isinstance(v, str)]
        values += [self.token or "", os.environ.get("AZURE_OPENAI_KEY", "")]
        try:
            from jira_agent.llm import _central_key
            values.append(str(_central_key.get("key") or ""))
        except Exception:
            pass
        return sorted({v for v in values if len(v) >= 8}, key=len, reverse=True)

    def finish(self, performance=None, result=None, error: BaseException | None = None) -> None:
        try:
            outcome = "completed" if error is None else (
                "cancelled" if isinstance(error, (GeneratorExit, KeyboardInterrupt)) or type(error).__name__ == "CancelledError"
                else "error")
            secrets = self._secrets()
            lines = [f"model: {self.model or '(not built)'} | history items sent: {self.history_items} | "
                     f"tools offered: {', '.join(self.tools) or '(none)'}",
                     "[system prompt]\n" + redact(self.prompt or "(not built)", secrets),
                     "[user] " + redact(self.user_text, secrets)]
            for item in list(getattr(result, "new_items", None) or []):
                try:
                    lines.append(format_item(item.to_input_item(), secrets))
                except Exception:
                    lines.append(f"[{type(item).__name__}] (could not be read)")
            if error is not None:
                detail = f"{type(error).__name__}: {error}".rstrip(": ")
                lines.append("[error] " + redact(detail, secrets, 4000))
            if performance is not None:
                lines.append("[performance] " + json.dumps(performance.summary(outcome), sort_keys=True))
            body = "\n".join(lines)
            _store(self.state, self.chat,
                   lambda number: f"=== Request {number} | {_utc(self.started)} | outcome: {outcome} ===\n{body}")
        except Exception:
            _log.warning("Chat log: could not record a request", exc_info=True)


def start(headers, conversation_id: str, messages: list[dict]) -> Recorder | None:
    """Begin recording a request. Returns None when there is no trusted user identity."""
    try:
        from jira_agent.runtime import identity, last_user_text

        email, token = identity(headers)
        if not email:
            if os.environ.get("DATABRICKS_APP_NAME"):
                return None
            email = "local"
        return Recorder(user_state(email), email, conversation_id or NO_CHAT, last_user_text(messages), len(messages), token)
    except Exception:
        _log.warning("Chat log: could not start", exc_info=True)
        return None


def _store(state, chat: str, build) -> None:
    with _lock:
        logs = state.chat_logs
        log = logs.pop(chat, None) or {"entries": [], "chars": 0, "count": 0, "dropped": 0}
        log["count"] += 1
        entry = build(log["count"])
        log["entries"].append(entry)
        log["chars"] += len(entry)
        while log["chars"] > MAX_CHARS_PER_CHAT and len(log["entries"]) > 1:
            log["chars"] -= len(log["entries"].pop(0))
            log["dropped"] += 1
        logs[chat] = log                      # most recently used chat goes last
        while len(logs) > MAX_CHATS:
            logs.pop(next(iter(logs)))


def render(state, email: str, chat: str | None = None) -> tuple[str, str] | None:
    """The log file text and chat id for one chat, or the most recent chat if none is named."""
    with _lock:
        logs = state.chat_logs
        chat = chat or (next(reversed(logs)) if logs else None)
        log = logs.get(chat) if chat else None
        if not log:
            return None
        entries, dropped, count = list(log["entries"]), log["dropped"], log["count"]
    head = [
        "Jira Agent chat log",
        f"App version: {__version__} | exported: {_utc()} | chat id: {chat} | user: {email}",
        f"Requests recorded: {count}" + (f" (the {dropped} oldest were dropped to stay within the size limit)" if dropped else ""),
        "Kept in memory only: lost when the app restarts or the session expires. Keys and tokens are masked and image data",
        "is omitted, but ticket, file and table content is included as it was. Check the file before you share it.",
    ]
    return "\n".join(head) + "\n\n" + "\n\n".join(entries) + "\n", chat
