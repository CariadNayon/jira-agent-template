"""Endpunkte für das Zahnrad (Keys, Einstellungen, Unity Catalog), Downloads und das Einblenden des Zahnrads.

Alle Routen liegen unter /jira/* und werden von der MLflow-Proxy-Middleware NICHT an die Chat-UI
weitergereicht (registrierte Routen haben Vorrang). Keys kommen nur über /jira/api/credentials –
nicht über /invocations bzw. /responses – und tauchen dadurch nie in Traces auf.
"""
from __future__ import annotations

import asyncio
from pathlib import Path

from fastapi import APIRouter, FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, Response
from pydantic import BaseModel

from jira_agent import CFG
from jira_agent.jira_client import JiraClient, JiraError
from jira_agent.llm import PROVIDERS, check_azure_endpoint
from jira_agent.runtime import DEFAULT_SETTINGS, agent_name, default_agent_name, identity, load_settings, user_client
from jira_agent.settings_store import SettingsStore, sanitize
from jira_agent.state import get_file, logout, user_state

_STATIC = Path(__file__).parent / "static"
_UI_TAG = b'<script src="/jira/static/ui.js" defer></script>'
_CSP = "img-src 'self' data: blob:"

router = APIRouter(prefix="/jira")


def _who(request: Request) -> tuple[str, str | None]:
    email, token = identity(request.headers)
    if not email:
        raise HTTPException(401, "Nicht angemeldet.")
    return email, token


def _client(token: str | None):
    if not token:
        raise HTTPException(403, "Kein Nutzer-Token – User Authorization der App prüfen.")
    return user_client(token)


# ---------------------------------------------------------------- Status
@router.get("/api/me")
async def me(request: Request):
    email, token = _who(request)
    state = user_state(email)
    settings = await asyncio.to_thread(load_settings, state, email, token)
    return {
        "email": email,
        "jira_user": state.jira_user,
        "agent_name": agent_name(state, settings),
        "agent_name_default": default_agent_name(state.jira_display_name),
        "has_jira_token": bool(state.creds.get("jira_token")),
        "has_azure_key": bool(state.creds.get("azure_key")),
        "settings": settings,
        "defaults": {"rules": DEFAULT_SETTINGS["rules"], "azure_endpoint": CFG["llm"]["azure_endpoint"],
                     "azure_deployment": CFG["llm"]["deployment"], "azure_api_version": CFG["llm"]["api_version"]},
        "providers": [{"name": p.name, "label": p.label, "needs_own_key": p.needs_own_key}
                      for p in PROVIDERS.values()],
    }


# ---------------------------------------------------------------- Keys (nur Speicher)
class Credentials(BaseModel):
    jira_token: str | None = None
    azure_key: str | None = None


@router.post("/api/credentials")
async def set_credentials(body: Credentials, request: Request):
    email, _ = _who(request)
    state = user_state(email)
    result = {}
    if body.jira_token:
        try:
            me_ = await asyncio.to_thread(JiraClient(CFG["jira"]["base_url"], body.jira_token).myself)
        except JiraError as e:
            raise HTTPException(400, str(e)) from None
        state.creds["jira_token"] = body.jira_token
        state.jira_user = f"{me_.get('name')} | {me_.get('displayName')}"
        state.jira_display_name = me_.get("displayName")
        result["jira_user"] = state.jira_user
    if body.azure_key:
        state.creds["azure_key"] = body.azure_key
        result["azure_key"] = "gesetzt"
    return result


@router.delete("/api/credentials")
async def delete_credentials(request: Request):
    email, _ = _who(request)
    logout(email)
    return {"status": "abgemeldet"}


# ---------------------------------------------------------------- Einstellungen (Home-Ordner, ohne Keys)
class Settings(BaseModel):
    agent_name: str = ""
    rules: str = ""
    selected_tables: list[str] = []
    llm_provider: str = CFG["llm"]["provider"]
    azure_endpoint: str = ""
    azure_deployment: str = ""
    azure_api_version: str = ""


@router.post("/api/settings")
async def save_settings(body: Settings, request: Request):
    email, token = _who(request)
    if body.llm_provider not in PROVIDERS:
        raise HTTPException(400, "Unbekanntes Modell.")
    data = body.model_dump()
    if PROVIDERS[body.llm_provider].needs_own_key:
        try:
            check_azure_endpoint(body.azure_endpoint or CFG["llm"]["azure_endpoint"])
        except ValueError as e:
            raise HTTPException(400, str(e)) from None
    else:
        data["azure_endpoint"] = ""
    settings = {**DEFAULT_SETTINGS, **sanitize(data)}
    saved = False
    if token:
        try:
            await asyncio.to_thread(SettingsStore(user_client(token), email).save, settings)
            saved = True
        except Exception as e:
            user_state(email).settings = settings
            return {"settings": settings, "saved": False, "warning": f"Nur für diese Sitzung: {type(e).__name__}"}
    user_state(email).settings = settings
    return {"settings": settings, "saved": saved}


# ---------------------------------------------------------------- Unity Catalog (Nutzerrechte)
@router.get("/api/uc/catalogs")
async def uc_catalogs(request: Request):
    w = _client(_who(request)[1])
    return sorted(c.name for c in await asyncio.to_thread(lambda: list(w.catalogs.list())))


@router.get("/api/uc/schemas")
async def uc_schemas(catalog: str, request: Request):
    w = _client(_who(request)[1])
    return sorted(s.name for s in await asyncio.to_thread(lambda: list(w.schemas.list(catalog_name=catalog))))


@router.get("/api/uc/tables")
async def uc_tables(catalog: str, schema: str, request: Request):
    w = _client(_who(request)[1])
    return sorted(t.name for t in await asyncio.to_thread(
        lambda: list(w.tables.list(catalog_name=catalog, schema_name=schema))))


# ---------------------------------------------------------------- Dateien (nur für den Besitzer)
@router.get("/files/{fid}")
async def download(fid: str, request: Request):
    email, _ = _who(request)
    f = get_file(email, fid)
    if f is None:
        raise HTTPException(404, "Datei nicht gefunden oder abgelaufen.")
    disposition = "inline" if f.mime.startswith("image/") else "attachment"
    return Response(f.data, media_type=f.mime, headers={
        "Content-Disposition": f'{disposition}; filename="{f.name}"', "Cache-Control": "private, no-store"})


# ---------------------------------------------------------------- Oberfläche
@router.get("/settings", response_class=HTMLResponse)
async def settings_page():
    return HTMLResponse((_STATIC / "settings.html").read_text(encoding="utf-8"))


@router.get("/guide", response_class=HTMLResponse)
async def guide_page():
    return HTMLResponse((_STATIC / "guide.html").read_text(encoding="utf-8"))


@router.get("/static/ui.js")
async def ui_js():
    return Response((_STATIC / "ui.js").read_text(encoding="utf-8"), media_type="application/javascript",
                    headers={"Cache-Control": "no-cache"})


def inject_ui(html: bytes) -> bytes:
    if _UI_TAG in html:
        return html
    idx = html.lower().rfind(b"</body>")
    return html[:idx] + _UI_TAG + html[idx:] if idx >= 0 else html + _UI_TAG


def install(app: FastAPI) -> None:
    """Registriert die Routen und fügt ui.js (Zahnrad, Anleitung, Layout) in die HTML-Seiten der Chat-UI ein."""
    # Routen einzeln registrieren statt app.include_router(router): Neuere FastAPI-Versionen legen
    # eingebundene Router gebündelt ab (ohne path_regex), dann erkennt die Chat-Proxy-Middleware von
    # MLflow sie nicht und antwortet mit "Not found".
    for r in router.routes:
        app.add_api_route(r.path, r.endpoint, methods=sorted(r.methods), response_class=r.response_class,
                          name=r.name, include_in_schema=False)

    @app.middleware("http")
    async def ui_injection(request: Request, call_next):
        path = request.url.path
        is_page = request.method == "GET" and (path == "/" or path.startswith("/chat"))
        if is_page:
            # Ohne bedingte Anfrage antwortet die Chat-UI nie mit "304 Not Modified" – sonst zeigt der
            # Browser seine alte, zwischengespeicherte Seite ohne ui.js.
            request.scope["headers"] = [(k, v) for k, v in request.scope["headers"]
                                        if k.lower() not in (b"if-none-match", b"if-modified-since")]
        response = await call_next(request)
        if not is_page or "text/html" not in response.headers.get("content-type", ""):
            return response
        body = b"".join([chunk async for chunk in response.body_iterator])
        headers = {k: v for k, v in response.headers.items()
                   if k.lower() not in ("content-length", "content-encoding", "etag", "last-modified")}
        headers["cache-control"] = "no-store"
        # Bilder nur von der App selbst: verhindert, dass ein (z. B. per Prompt-Injection aus einem Ticket)
        # erzeugtes Markdown-Bild Daten über die URL an fremde Server schickt.
        headers["content-security-policy"] = _CSP
        return Response(inject_ui(body), status_code=response.status_code, headers=headers)
