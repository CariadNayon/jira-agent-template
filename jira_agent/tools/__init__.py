"""Tool-Registry. Jede Datei in diesem Ordner wird automatisch geladen.

Eigenes Tool hinzufügen: neue Datei anlegen und eine Funktion mit @tool dekorieren.
Die Funktion bekommt als erstes Argument den ToolContext (ctx), danach ihre Parameter.
Schreib-Tools mit write=True markieren – die Bestätigung "ja <CODE>" kommt dann automatisch.
needs=["jira"|"sql"|"files"] blendet ein Tool aus, solange die Voraussetzung fehlt.
Siehe example_custom_tool.py.
"""
from __future__ import annotations

import importlib
import pkgutil
from dataclasses import dataclass, field
from typing import Any, Callable


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


def tool(description: str, parameters: dict | None = None, required: tuple | list = (),
         write: bool = False, needs: tuple | list = (), name: str | None = None):
    """Registriert eine Funktion als Tool für den Agenten."""
    def deco(fn: Callable) -> Callable:
        tool_name = name or fn.__name__
        existing = REGISTRY.get(tool_name)
        if existing and existing.func.__module__ != fn.__module__:
            raise ValueError(f"Tool-Name doppelt vergeben: {tool_name}")
        REGISTRY[tool_name] = Tool(tool_name, description, parameters or {}, tuple(required),
                                   fn, write, tuple(needs))
        return fn
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
