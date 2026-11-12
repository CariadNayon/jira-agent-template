"""Adapter: Tool-Registry -> FunctionTools des OpenAI Agents SDK, mit erzwungener Bestätigung.

Schreib-Tools (write=True) laufen nur, wenn
  1. das Modell den richtigen confirmation_code mitschickt UND
  2. genau dieser Code in der letzten Nachricht des Nutzers steht ("ja <CODE>").
Der Code ist ein HMAC über Tool-Name + Argumente mit einem Geheimnis pro Nutzer-Sitzung –
das Modell kann ihn nicht selbst berechnen, und er gilt nur für genau diese Aktion.
"""
from __future__ import annotations

import asyncio
import functools
import hashlib
import hmac
import json
import re

from jira_agent.tools import REGISTRY, Tool, ToolContext, json_schema, load_tools

_MAX_OUTPUT = 20000


class RunContext:
    """Kontext für Runner.run(context=...). Bewusst ohne aussagekräftiges repr (Traces)."""

    __slots__ = ("tool_ctx", "_secret", "last_user_text")

    def __init__(self, tool_ctx: ToolContext, secret: bytes, last_user_text: str):
        self.tool_ctx = tool_ctx
        self._secret = secret
        self.last_user_text = last_user_text or ""

    def __repr__(self) -> str:
        return "RunContext()"

    def code_for(self, name: str, args: dict) -> str:
        payload = f"{name}|{json.dumps(args, sort_keys=True, ensure_ascii=False)}".encode()
        return hmac.new(self._secret, payload, hashlib.sha256).hexdigest()[:6].upper()


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


def execute(t: Tool, rc: RunContext, args: dict) -> dict:
    """Führt ein Tool aus (synchron, testbar). Fehler gehen als Text an das Modell zurück."""
    try:
        if t.write:
            given = str(args.pop("confirmation_code", "") or "").upper()
            code = rc.code_for(t.name, args)
            if given != code or not re.fullmatch(r"\s*ja\s+" + re.escape(code) + r"\s*[.!]?\s*", rc.last_user_text, re.I):
                return {"status": "BESTAETIGUNG_NOETIG", "tool": t.name, "argumente": args, "code": code,
                        "hinweis": f"Zeige dem Nutzer genau diese Aktion und bitte um die Antwort 'ja {code}'."}
        return t.func(rc.tool_ctx, **args)
    except Exception as e:
        return {"error": type(e).__name__, "details": str(e)[:300]}


async def _on_invoke(t: Tool, ctx, arguments: str) -> str:
    try:
        args = json.loads(arguments or "{}")
        if not isinstance(args, dict):
            raise ValueError("Argumente müssen ein JSON-Objekt sein.")
    except Exception as e:
        result = {"error": type(e).__name__, "details": str(e)[:200]}
    else:
        result = await asyncio.to_thread(execute, t, ctx.context, args)   # Tools sind blockierend
    encoded = json.dumps(result, ensure_ascii=False, default=str)
    if len(encoded) > _MAX_OUTPUT:
        # Never cut JSON midway through a string/list. Metadata tools support field/value filters.
        encoded = json.dumps({"status": "RESULT_TOO_LARGE", "truncated": True,
                              "hint": "Ergebnis eingrenzen (field_id, value_query, max_results) und erneut lesen. "
                                      "Eine ausgeführte Schreibaktion nicht wiederholen.",
                              "preview": encoded[:12000]}, ensure_ascii=False)
    return encoded


def build_function_tools(tool_ctx: ToolContext) -> list:
    from agents import FunctionTool

    return [FunctionTool(name=t.name, description=t.description, params_json_schema=json_schema(t),
                         on_invoke_tool=functools.partial(_on_invoke, t), strict_json_schema=False)
            for t in available_tools(tool_ctx)]
