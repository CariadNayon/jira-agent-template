"""Tool-Registry. Jede Datei in diesem Ordner wird automatisch geladen.

Eigenes Tool hinzufügen: neue Datei anlegen und eine Funktion mit @tool dekorieren.

    @tool(write=True, needs=["jira"])
    def jira_add_label(ctx: ToolContext, issue_key: str, label: str) -> dict:
        \"\"\"Setzt ein Label an einem Jira-Ticket.

        issue_key: Ticket-Key, z. B. ABC-123
        label: Label ohne Leerzeichen
        \"\"\"
        ctx.jira.add_label(issue_key, label)
        return {"status": "OK"}

- Erster Satz/Absatz des Docstrings = Beschreibung für das Modell.
- Zeilen "name: Text" im Docstring = Beschreibung des Parameters.
- Typen aus den Type-Hints (str, int, float, bool, list[str], Literal["a", "b"]); ohne Standardwert = Pflicht.
- Erstes Argument ist immer ctx (ToolContext): ctx.jira, ctx.sql, ctx.files, ctx.selected_tables.
- write=True: Der Agent muss vorher "ja <CODE>" einholen (im Code erzwungen).
- needs=["jira"|"sql"|"files"] blendet ein Tool aus, solange die Voraussetzung fehlt.
Siehe example_custom_tool.py.
"""
from __future__ import annotations

import importlib
import inspect
import pkgutil
import re
import types
import typing
from dataclasses import dataclass, field
from typing import Any, Callable, Literal, Union


@dataclass(repr=False)
class ToolContext:
    jira: Any = None                 # JiraClient der Sitzung (oder None)
    sql: Any = None                  # SqlRunner mit Nutzerrechten (oder None)
    files: Any = None                # FileSink des Nutzers für Diagramme/Exporte (oder None)
    selected_tables: list[str] = field(default_factory=list)

    def __repr__(self) -> str:      # keine Clients/Keys in Traces
        return f"ToolContext(jira={self.jira is not None}, sql={self.sql is not None}, tables={len(self.selected_tables)})"


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    parameters: dict
    required: tuple
    func: Callable
    write: bool = False
    needs: tuple = ()


REGISTRY: dict[str, Tool] = {}

_PRIMITIVES = {str: "string", int: "integer", float: "number", bool: "boolean", dict: "object"}


def _schema_for(hint: Any) -> dict:
    origin = typing.get_origin(hint)
    if origin in (Union, types.UnionType):
        args = [a for a in typing.get_args(hint) if a is not type(None)]
        return _schema_for(args[0]) if len(args) == 1 else {}
    if origin is Literal:
        values = list(typing.get_args(hint))
        return {"type": _PRIMITIVES.get(type(values[0]), "string"), "enum": values}
    if origin in (list, tuple, set) or hint in (list, tuple, set):
        item_args = typing.get_args(hint)
        return {"type": "array", "items": _schema_for(item_args[0]) if item_args else {}}
    if origin is dict:
        return {"type": "object"}
    return {"type": _PRIMITIVES[hint]} if hint in _PRIMITIVES else {}


def _parse_docstring(doc: str, param_names: list[str]) -> tuple[str, dict[str, str]]:
    """Trennt Beschreibung und Zeilen der Form 'name: Text' (auch nach 'Args:')."""
    description, params, current = [], {}, None
    for line in inspect.cleandoc(doc or "").splitlines():
        m = re.match(r"\s*(\w+)\s*(?:\([^)]*\))?\s*:\s*(.*)", line)
        if m and m.group(1) in param_names:
            current = m.group(1)
            params[current] = m.group(2).strip()
        elif current and line.strip():
            params[current] += " " + line.strip()
        elif line.strip().lower() in ("args:", "parameter:", "parameters:"):
            continue
        elif current is None:
            description.append(line)
        else:
            current = None
    return "\n".join(description).strip(), params


def infer_schema(fn: Callable) -> tuple[str, dict, tuple]:
    """(Beschreibung, Parameter-Schema, Pflichtfelder) aus Signatur, Type-Hints und Docstring."""
    sig = inspect.signature(fn)
    names = list(sig.parameters)[1:]  # erstes Argument ist ctx
    hints = typing.get_type_hints(fn)
    description, docs = _parse_docstring(fn.__doc__ or "", names)
    props, required = {}, []
    for n in names:
        p = sig.parameters[n]
        if p.kind in (p.VAR_POSITIONAL, p.VAR_KEYWORD):
            continue
        schema = _schema_for(hints.get(n, str))
        if n in docs:
            schema["description"] = docs[n]
        props[n] = schema
        if p.default is inspect.Parameter.empty:
            required.append(n)
    return description, props, tuple(required)


def tool(description: str | Callable | None = None, parameters: dict | None = None, required: tuple | list = (),
         write: bool = False, needs: tuple | list = (), name: str | None = None):
    """Registriert eine Funktion als Tool für den Agenten.

    Kurzform: @tool oder @tool(write=True, needs=["jira"]) – Beschreibung und Parameter kommen aus
    Docstring und Type-Hints. Langform (explizites JSON-Schema) bleibt möglich:
    @tool("Beschreibung", {"x": {"type": "string"}}, ["x"]).
    """
    def deco(fn: Callable) -> Callable:
        tool_name = name or fn.__name__
        desc, params, req = (description, parameters, tuple(required)) if parameters is not None else (None, None, None)
        if params is None:
            doc_desc, params, req = infer_schema(fn)
            desc = description if isinstance(description, str) and description else doc_desc
        if not desc:
            raise ValueError(f"Tool {tool_name}: Beschreibung fehlt (Docstring ergänzen).")
        existing = REGISTRY.get(tool_name)
        if existing and existing.func.__module__ != fn.__module__:
            raise ValueError(f"Tool-Name doppelt vergeben: {tool_name}")
        REGISTRY[tool_name] = Tool(tool_name, desc, params, req, fn, write, tuple(needs))
        return fn

    if callable(description):  # @tool ohne Klammern
        fn, description = description, None
        return deco(fn)
    return deco


def load_tools() -> dict[str, Tool]:
    """Importiert alle Module in jira_agent/tools (außer solchen, die mit _ beginnen)."""
    for mod in pkgutil.iter_modules(__path__):
        if not mod.name.startswith("_"):
            importlib.import_module(f"{__name__}.{mod.name}")
    return REGISTRY


def json_schema(t: Tool) -> dict:
    props = dict(t.parameters)
    if t.write:
        props["confirmation_code"] = {
            "type": "string",
            "description": "Nur setzen, nachdem der Nutzer mit 'ja <CODE>' bestätigt hat. Beim ersten Aufruf weglassen."}
    return {"type": "object", "properties": props, "required": list(t.required)}
