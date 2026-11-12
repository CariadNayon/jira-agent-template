"""Modell-Provider für das OpenAI Agents SDK. Weitere Provider mit @provider ergänzen.

Jeder Provider bekommt die LLM-Konfiguration (cfg), die Einstellungen des Nutzers (settings) und
seine Keys dieser Sitzung (creds) und liefert ein Modell-Objekt für Agent(model=...).
"""
from __future__ import annotations

import os
import re
import time
from dataclasses import dataclass
from typing import Callable

from jira_agent import BUNDLE
from jira_agent.secrets import get_app_secret


@dataclass(frozen=True)
class Provider:
    name: str
    label: str
    build: Callable
    needs_own_key: bool = False


PROVIDERS: dict[str, Provider] = {}


def provider(name: str, label: str, needs_own_key: bool = False):
    def deco(fn: Callable) -> Callable:
        PROVIDERS[name] = Provider(name, label, fn, needs_own_key)
        return fn
    return deco


# Eigene Endpoints nur bei Azure OpenAI zulassen (verhindert Aufrufe beliebiger URLs aus der App).
_AZURE_ENDPOINT_RE = re.compile(r"https://[a-z0-9\-]+\.(openai\.azure\.com|cognitiveservices\.azure\.com)/?")


def check_azure_endpoint(endpoint: str) -> str:
    if not _AZURE_ENDPOINT_RE.fullmatch(endpoint or ""):
        raise ValueError("Endpoint muss https://<name>.openai.azure.com oder .cognitiveservices.azure.com sein.")
    return endpoint


def _azure_model(api_key: str, endpoint: str, api_version: str, deployment: str):
    from agents import OpenAIChatCompletionsModel
    from openai import AsyncAzureOpenAI

    client = AsyncAzureOpenAI(api_key=api_key, api_version=api_version, azure_endpoint=endpoint)
    return OpenAIChatCompletionsModel(model=deployment, openai_client=client)


_central_key: dict[str, object] = {}
_CENTRAL_KEY_TTL = 15 * 60  # Sekunden; danach neu lesen, damit eine Key-Rotation ohne Neustart greift


def central_key(cfg: dict) -> str:
    if time.time() - float(_central_key.get("loaded", 0)) > _CENTRAL_KEY_TTL:
        # Bevorzugt: Secret als App-Ressource (Umgebungsvariable), sonst direkt aus dem Scope in databricks.yml.
        _central_key["key"] = os.environ.get("AZURE_OPENAI_KEY") or get_app_secret(BUNDLE["secret_key"],
                                                                                    BUNDLE["secret_scope"])
        _central_key["loaded"] = time.time()
    return str(_central_key["key"])


@provider("azure_central", "Azure OpenAI (Team-Key)")
def _azure_central(cfg: dict, settings: dict, creds: dict):
    return _azure_model(central_key(cfg), cfg["azure_endpoint"],
                        settings.get("azure_api_version") or cfg["api_version"],
                        settings.get("azure_deployment") or cfg["deployment"])


@provider("azure_own", "Azure OpenAI (eigener Key)", needs_own_key=True)
def _azure_own(cfg: dict, settings: dict, creds: dict):
    api_key = creds.get("azure_key")
    if not api_key:
        raise RuntimeError("Bitte über das Zahnrad unter Zugänge einen eigenen Azure-Key eintragen.")
    return _azure_model(api_key, check_azure_endpoint(settings.get("azure_endpoint") or cfg["azure_endpoint"]),
                        settings.get("azure_api_version") or cfg["api_version"],
                        settings.get("azure_deployment") or cfg["deployment"])


def build_model(name: str, cfg: dict, settings: dict, creds: dict):
    if name not in PROVIDERS:
        raise ValueError(f"Unbekannter LLM-Provider: {name}")
    return PROVIDERS[name].build(cfg, settings, creds)
