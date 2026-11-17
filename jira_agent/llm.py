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
        raise ValueError("Endpoint must be https://<name>.openai.azure.com or .cognitiveservices.azure.com.")
    return endpoint


def _azure_model(api_key: str, endpoint: str, api_version: str, deployment: str, *,
                 max_retries: int = 2, retry_wait_seconds: float = 30, timeout_seconds: float = 60):
    from agents import OpenAIChatCompletionsModel
    from jira_agent.model_client import BoundedAzureClient
    from jira_agent.connections import azure_http_client

    http_client = azure_http_client()
    client = BoundedAzureClient(api_key=api_key, api_version=api_version, azure_endpoint=endpoint,
                             max_retries=max_retries, retry_wait_seconds=retry_wait_seconds, timeout=timeout_seconds,
                             **({'http_client': http_client} if http_client is not None else {}))
    model = OpenAIChatCompletionsModel(model=deployment, openai_client=client)
    model._jira_agent_client = client  # This factory owns one SDK client per run.
    return model


_central_key: dict[str, object] = {}
_CENTRAL_KEY_TTL = 15 * 60  # Sekunden; danach neu lesen, damit eine Key-Rotation ohne Neustart greift


def central_key(cfg: dict) -> str:
    if time.time() - float(_central_key.get("loaded", 0)) > _CENTRAL_KEY_TTL:
        # Bevorzugt: Secret als App-Ressource (Umgebungsvariable), sonst direkt aus dem Scope in databricks.yml.
        _central_key["key"] = os.environ.get("AZURE_OPENAI_KEY") or get_app_secret(BUNDLE["secret_key"],
                                                                                    BUNDLE["secret_scope"])
        _central_key["loaded"] = time.time()
    return str(_central_key["key"])


@provider("azure_central", "Azure OpenAI (team key)")
def _azure_central(cfg: dict, settings: dict, creds: dict):
    return _azure_model(central_key(cfg), cfg["azure_endpoint"],
                        settings.get("azure_api_version") or cfg["api_version"],
                        settings.get("azure_deployment") or cfg["deployment"], **_retry_settings(cfg))


@provider("azure_own", "Azure OpenAI (your own key)", needs_own_key=True)
def _azure_own(cfg: dict, settings: dict, creds: dict):
    api_key = creds.get("azure_key")
    if not api_key:
        raise RuntimeError("Please enter your own Azure key under Settings → Connections.")
    return _azure_model(api_key, check_azure_endpoint(settings.get("azure_endpoint") or cfg["azure_endpoint"]),
                        settings.get("azure_api_version") or cfg["api_version"],
                        settings.get("azure_deployment") or cfg["deployment"], **_retry_settings(cfg))


def _retry_settings(cfg: dict) -> dict:
    return {'max_retries': cfg.get('max_retries', 2),
            'retry_wait_seconds': cfg.get('retry_wait_seconds', 30),
            'timeout_seconds': cfg.get('timeout_seconds', 60)}


def build_model(name: str, cfg: dict, settings: dict, creds: dict):
    if name not in PROVIDERS:
        raise ValueError(f"Unknown LLM provider: {name}")
    return PROVIDERS[name].build(cfg, settings, creds)
