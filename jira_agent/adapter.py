"""Adapter: Tool-Registry -> FunctionTools des OpenAI Agents SDK, mit erzwungener Bestätigung.

Schreib-Tools (write=True) laufen nur, wenn
  1. das Modell den richtigen confirmation_code mitschickt UND
  2. genau dieser Code in der letzten Nachricht des Nutzers steht ("ja <CODE>").
Der Code gehört zu einem zufälligen, einmaligen Vorschlag. Er ist an Sitzung, Gespräch, Tool und
Argumente gebunden. Ein Aktionsbeleg verhindert doppelte Ausführung während derselben Sitzung.
"""
from __future__ import annotations

import asyncio
import base64
import functools
import hashlib
import hmac
import json
import re

from jira_agent.approvals import ActionLedger
from jira_agent.visual_output import VisualResult
from jira_agent.tools import REGISTRY, Tool, ToolContext, json_schema, load_tools

_MAX_OUTPUT = 20000


class RunContext:
    """Kontext für Runner.run(context=...). Bewusst ohne aussagekräftiges repr (Traces)."""

    __slots__ = ("tool_ctx", "_secret", "last_user_text", "actions", "conversation_id")

    def __init__(self, tool_ctx: ToolContext, secret: bytes, last_user_text: str, *,
                 actions: ActionLedger | None = None, conversation_id: str = ""):
        self.tool_ctx = tool_ctx
        self._secret = secret
        self.last_user_text = last_user_text or ""
        self.actions = actions if actions is not None else ActionLedger()
        self.conversation_id = conversation_id

    def __repr__(self) -> str:
        return "RunContext()"

    def fingerprint(self, name: str, args: dict) -> str:
        payload = json.dumps([self.conversation_id, name, args], sort_keys=True, ensure_ascii=False).encode()
        return hmac.new(self._secret, payload, hashlib.sha256).hexdigest()


def available_tools(tool_ctx: ToolContext) -> list[Tool]:
    load_tools()
    selected = tool_ctx.enabled_tools
    if selected is not None:
        if not isinstance(selected, list) or any(not isinstance(name, str) for name in selected):
            raise ValueError("agent.enabled_tools muss null oder eine Liste von Tool-Namen sein.")
        unknown = set(selected) - REGISTRY.keys()
        if unknown:
            raise ValueError(f"Unbekannte Tools in agent.enabled_tools: {sorted(unknown)}")
    return [t for t in REGISTRY.values() if (selected is None or t.name in selected)
            and all(getattr(tool_ctx, n, None) for n in t.needs)]


def execute(t: Tool, rc: RunContext, args: dict) -> dict | VisualResult:
    """Execute writes once per explicit approval, including across retries/concurrent requests."""
    claimed_code = None
    try:
        args = dict(args)  # do not mutate callers' arguments when removing the confirmation
        if t.write:
            given = str(args.pop("confirmation_code", "") or "").upper()
            fingerprint = rc.fingerprint(t.name, args)
            approval = re.fullmatch(r"\s*ja\s+([A-F0-9]{6})\s*[.!]?\s*", rc.last_user_text, re.I)
            if approval and given == approval.group(1).upper():
                claimed, receipt = rc.actions.claim(given, fingerprint)
                if receipt is not None:
                    return receipt
                if claimed:
                    claimed_code = given
            if claimed_code is None:
                code, receipt = rc.actions.propose(fingerprint, rc._secret, confirmation_message=bool(approval))
                if receipt is not None:
                    return receipt
                return {"status": "BESTAETIGUNG_NOETIG", "tool": t.name, "argumente": args, "code": code,
                        "expires_in_seconds": 600,
                        "hinweis": f"Zeige dem Nutzer genau diese Aktion und bitte um die Antwort 'ja {code}'. "
                                   "Die Bestätigung ist einmalig und 10 Minuten gültig."}
        result = t.func(rc.tool_ctx, **args)
        if claimed_code is not None:
            if "error" in result:
                result = {**result, "outcome": "unverified", "hinweis": "Vor einer Wiederholung im Zielsystem prüfen."}
            rc.actions.finish(claimed_code, result, uncertain="error" in result)
        return result
    except Exception as e:
        result = {"error": type(e).__name__, "details": str(e)[:300]}
        if claimed_code is not None:
            # A timeout/error does not prove that the external write failed. Keep the claim consumed.
            result.update({"outcome": "unverified", "hinweis": "Nicht automatisch erneut ausführen. "
                           "Zuerst im Zielsystem prüfen, ob die Änderung übernommen wurde."})
            rc.actions.finish(claimed_code, result, uncertain=True)
        return result


async def _on_invoke(t: Tool, ctx, arguments: str) -> str | list:
    try:
        args = json.loads(arguments or "{}")
        if not isinstance(args, dict):
            raise ValueError("Argumente müssen ein JSON-Objekt sein.")
    except Exception as e:
        result = {"error": type(e).__name__, "details": str(e)[:200]}
    else:
        result = await asyncio.to_thread(execute, t, ctx.context, args)   # Tools sind blockierend
    if isinstance(result, VisualResult):
        from agents.tool import ToolOutputText, ToolOutputImage
        content = [ToolOutputText(text=json.dumps(result.metadata,ensure_ascii=False,default=str))]
        for image in result.images:
            content.append(ToolOutputText(text=f"PDF Seite {image.page}"))
            content.append(ToolOutputImage(image_url=f"data:{image.mime};base64," + base64.b64encode(image.data).decode('ascii'),detail="high"))
        return content
    encoded = json.dumps(result, ensure_ascii=False, default=str)
    if len(encoded) > _MAX_OUTPUT:
        # Never cut JSON midway through a string/list. Metadata tools support field/value filters.
        encoded = json.dumps({"status": "RESULT_TOO_LARGE", "truncated": True,
                              "hint": "Ergebnis eingrenzen (field_id, value_query, columns, max_rows, max_results) und erneut lesen. "
                                      "Eine ausgeführte Schreibaktion nicht wiederholen.",
                              "preview": encoded[:12000]}, ensure_ascii=False)
    return encoded


def build_function_tools(tool_ctx: ToolContext) -> list:
    from agents import FunctionTool

    return [FunctionTool(name=t.name, description=t.description, params_json_schema=json_schema(t),
                         on_invoke_tool=functools.partial(_on_invoke, t), strict_json_schema=False)
            for t in available_tools(tool_ctx)]
