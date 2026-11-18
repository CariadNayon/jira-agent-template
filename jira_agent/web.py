"""Endpunkte für das Zahnrad (Keys, Einstellungen, Unity Catalog), Downloads und das Einblenden des Zahnrads.

Alle Routen liegen unter /jira/* und werden von der MLflow-Proxy-Middleware NICHT an die Chat-UI
weitergereicht (registrierte Routen haben Vorrang). Keys kommen nur über /jira/api/credentials –
nicht über /invocations bzw. /responses – und tauchen dadurch nie in Traces auf.
"""
from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path
from urllib.parse import quote

from fastapi import APIRouter, FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, Response
from pydantic import BaseModel

from jira_agent import CFG, __version__, registry
from jira_agent.jira_client import JiraClient, JiraError
from jira_agent.llm import PROVIDERS, check_azure_endpoint
from jira_agent.runtime import (DEFAULT_SETTINGS, WAREHOUSE_ID, agent_name, all_skills, catalog_skills,
                                default_agent_name, identity, load_catalog_skill, load_personal_skills,
                                load_settings, user_client)
from jira_agent.settings_store import SettingsStore, sanitize
from jira_agent.skills import MAX_PERSONAL, PersonalSkillStore, check_skill, render_skill, team_skills
from jira_agent.state import UploadSink, get_file, logout, user_state
from jira_agent.uploads import validate_upload
from jira_agent.credentials import (JiraTokenStore, cipher, remember_availability, remember_days,
                                    restore_jira, set_jira_identity)

_STATIC = Path(__file__).parent / "static"
_UI_TAG = b'<script src="/jira/static/ui.js" defer></script>'
_CSP = "img-src 'self' data: blob:"
_IMG_RE = re.compile(r"[a-z0-9_\-]+\.png")
_UPLOAD_NAME_RE = re.compile(r"[^\w.\- ()äöüÄÖÜß]+")
_MAX_UPLOAD = 20 * 1024 * 1024

router = APIRouter(prefix="/jira")


def _who(request: Request) -> tuple[str, str | None]:
    email, token = identity(request.headers)
    if not email:
        raise HTTPException(401, "Not signed in.")
    return email, token


def _client(token: str | None):
    if not token:
        raise HTTPException(403, "No user token. Check the User Authorization settings for the app.")
    return user_client(token)


# ---------------------------------------------------------------- Status
@router.get("/api/me")
async def me(request: Request, response: Response):
    response.headers['Cache-Control'] = 'private, no-store'
    email, token = _who(request)
    state = user_state(email)
    await asyncio.to_thread(restore_jira, state, email, token)
    settings = await asyncio.to_thread(load_settings, state, email, token)
    remembering = remember_availability(token)
    return {
        "email": email,
        "app_version": __version__,
        "effective_deployment": settings.get('azure_deployment') or CFG['llm']['deployment'],
        "jira_user": state.jira_user,
        "agent_name": agent_name(state, settings),
        "agent_name_default": default_agent_name(state.jira_display_name),
        "has_jira_token": bool(state.creds.get("jira_token")),
        "has_azure_key": bool(state.creds.get("azure_key")),
        "remember_jira_available": remembering['available'],
        "remember_jira_reason": remembering['reason'],
        "remember_jira_message": remembering['message'],
        "remember_jira_days": remember_days(),
        "has_saved_jira_token": state.jira_saved,
        "jira_saved_until": state.jira_saved_until,
        "jira_connection_message": state.jira_connection_message,
        "settings": settings,
        "defaults": {"rules": DEFAULT_SETTINGS["rules"], "azure_endpoint": CFG["llm"]["azure_endpoint"],
                     "azure_deployment": CFG["llm"]["deployment"], "azure_api_version": CFG["llm"]["api_version"],
                     "detailed_deployment": CFG['llm'].get('detailed_deployment', CFG['llm']['deployment']),
                     "azure_deployments": CFG['llm'].get('deployments', [])},
        "providers": [{"name": p.name, "label": p.label, "needs_own_key": p.needs_own_key}
                      for p in PROVIDERS.values()],
    }


# ---------------------------------------------------------------- Keys (nur Speicher)
class Credentials(BaseModel):
    jira_token: str | None = None
    azure_key: str | None = None
    remember_jira: bool = False


def _connect_jira(state, email, user_token, jira_token, remember):
    with state.credential_lock:
        if remember and (cipher() is None or not user_token):
            raise HTTPException(400, 'Remembering Jira tokens is not available for this connection.')
        try:
            myself = JiraClient(CFG['jira']['base_url'], jira_token).myself()
            JiraClient.check_user(myself.get('name') or '')
        except (JiraError, ValueError, AttributeError) as exc:
            detail = str(exc) if isinstance(exc, JiraError) else 'Jira did not return a valid user identity.'
            raise HTTPException(400, detail) from None
        expires_at = None
        try:
            if remember:
                expires_at = JiraTokenStore(_client(user_token), email).save(jira_token)
            elif user_token and (cipher() is not None or state.jira_saved):
                # Replacing a remembered token with a session-only token must remove the old copy.
                JiraTokenStore(_client(user_token), email).delete()
            elif state.jira_saved:
                raise HTTPException(403, 'Sign in again to remove the previously saved Jira token.')
        except HTTPException:
            raise
        except Exception:
            raise HTTPException(502, 'The saved Jira connection could not be updated. Please try again.') from None
        set_jira_identity(state, jira_token, myself)
        state.jira_saved = remember
        state.jira_saved_until = expires_at
        state.jira_restore_checked = True
        state.jira_restore_retry_at = 0
        state.jira_connection_message = ''
        return {'jira_user': state.jira_user, 'jira_remembered': remember, 'jira_saved_until': expires_at}


@router.post("/api/credentials")
async def set_credentials(body: Credentials, request: Request, response: Response):
    response.headers['Cache-Control'] = 'private, no-store'
    email, user_token = _who(request)
    state = user_state(email)
    result = {}
    if body.jira_token:
        result.update(await asyncio.to_thread(_connect_jira, state, email, user_token,
                                              body.jira_token, body.remember_jira))
    if body.azure_key:
        state.creds["azure_key"] = body.azure_key
        result["azure_key"] = "set"
    return result


@router.delete("/api/credentials")
async def delete_credentials(request: Request, response: Response):
    response.headers['Cache-Control'] = 'private, no-store'
    email, user_token = _who(request)
    state = user_state(email)
    def forget():
        with state.credential_lock:
            removed = False
            if user_token:
                try:
                    JiraTokenStore(_client(user_token), email).delete()
                    removed = True
                except Exception:
                    # Ohne Remember-Funktion ist die Löschung nur ein Aufräumversuch und darf das Abmelden nicht blockieren.
                    if cipher() is not None or state.jira_saved:
                        raise HTTPException(502, 'The saved Jira token could not be deleted. Please try again.') from None
            elif state.jira_saved:
                raise HTTPException(403, 'Sign in again to forget the saved Jira token.')
            state.creds.clear()
            state.jira_user = state.jira_display_name = None
            state.jira_restore_checked = True
            state.jira_saved = False
            logout(email)
            return {'status': 'signed_out', 'saved_token_deleted': removed}
    return await asyncio.to_thread(forget)


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
        raise HTTPException(400, "Unknown model.")
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
            return {"settings": settings, "saved": False, "warning": f"For this session only: {type(e).__name__}"}
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
        raise HTTPException(404, "File not found or expired.")
    disposition = "inline" if f.mime.startswith("image/") else "attachment"
    return Response(f.data, media_type=f.mime, headers={
        "Content-Disposition": f'{disposition}; filename="{f.name}"', "Cache-Control": "private, no-store"})


# ---------------------------------------------------------------- Uploads (nur Speicher, nur für den Besitzer)
@router.post("/api/upload")
async def upload(name: str, request: Request, chat_id: str | None = None):
    """Rohdaten im Body, Dateiname als Query-Parameter (ohne multipart, keine Zusatzpakete nötig)."""
    email, _ = _who(request)
    if int(request.headers.get("content-length") or 0) > _MAX_UPLOAD:
        raise HTTPException(413, "File too large (max. 20 MB).")
    data = bytearray()
    async for chunk in request.stream():   # auch ohne Content-Length begrenzen
        data += chunk
        if len(data) > _MAX_UPLOAD:
            raise HTTPException(413, "File too large (max. 20 MB).")
    data = bytes(data)
    if not data:
        raise HTTPException(400, "Empty file.")
    clean = _UPLOAD_NAME_RE.sub("_", Path(name).name).strip()[:100] or "datei"
    mime = (request.headers.get("content-type") or "application/octet-stream").split(";")[0]
    if chat_id is not None and not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", chat_id):
        raise HTTPException(400, "Invalid conversation ID.")
    try:
        mime = await asyncio.to_thread(validate_upload, clean, mime, data,
                                       images_enabled=CFG["llm"].get("supports_images", False))
    except ValueError as e:
        raise HTTPException(415, str(e)) from None
    fid = UploadSink(email, conversation_id=chat_id).put(clean, mime, data)
    return {"id": fid, "name": clean, "bytes": len(data), "mime": mime,
            "reference": f"[File: {clean}](/jira/uploads/{fid})"}


@router.get("/uploads/{fid}")
async def uploaded_file(fid: str, request: Request):
    f = UploadSink(_who(request)[0]).get(fid)
    if f is None:
        raise HTTPException(404, "File not found or expired.")
    return Response(f.data, media_type=f.mime, headers={
        "Content-Disposition": f"attachment; filename*=UTF-8''{quote(f.name)}",
        "Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"})


@router.get("/api/uploads")
async def list_uploads(request: Request):
    return UploadSink(_who(request)[0]).list()


@router.delete("/api/uploads/{fid}")
async def delete_upload(fid: str, request: Request):
    UploadSink(_who(request)[0]).delete(fid)
    return {"status": "deleted"}


# ---------------------------------------------------------------- Skills (Team: Repo, persönlich: Home-Ordner)
class SkillBody(BaseModel):
    beschreibung: str = ""
    anleitung: str = ""


def _short_owner(owner: str | None) -> str:
    """'nayon.lenz@cariad.technology' -> 'nayon.lenz' (nur zur Anzeige)."""
    return (owner or "").split("@", 1)[0]


def _skill_list(skills: dict, catalog: dict | None = None, email: str = "") -> list[dict]:
    order = {"team": 0, "katalog": 1}
    rows = []
    for s in sorted(skills.values(), key=lambda s: (order.get(s["quelle"], 2), s["name"])):
        row = {"name": s["name"], "beschreibung": s["beschreibung"], "quelle": s["quelle"]}
        if s["quelle"] == "katalog":
            row.update(version=s["version"], owner=s.get("owner"), owner_name=_short_owner(s.get("owner")),
                       mine=(s.get("owner") or "").casefold() == email.casefold())
        elif s["quelle"] == "persoenlich" and catalog and s["name"] in catalog:
            # Der persönliche Skill verdeckt den Katalogeintrag gleichen Namens; hier bleibt der Stand sichtbar.
            published = catalog[s["name"]]
            row["published"] = {"version": published["version"], "owner": published.get("owner"),
                                "owner_name": _short_owner(published.get("owner")),
                                "mine": (published.get("owner") or "").casefold() == email.casefold()}
        rows.append(row)
    return rows


@router.get("/api/skills")
async def list_skills(request: Request):
    email, token = _who(request)
    state = user_state(email)
    own = await asyncio.to_thread(all_skills, state, email, token)
    catalog = await asyncio.to_thread(catalog_skills, state, token)
    return _skill_list({**catalog, **own}, catalog, email)


async def _find_skill(name: str, request: Request) -> dict | None:
    email, token = _who(request)
    state = user_state(email)
    skill = (await asyncio.to_thread(all_skills, state, email, token)).get(name)
    if skill:
        return skill
    if not registry.enabled():
        return None
    try:
        return await asyncio.to_thread(load_catalog_skill, state, token, name)
    except registry.RegistryError as e:
        raise HTTPException(502, str(e)) from None


@router.get("/api/skills/{name}")
async def get_skill(name: str, request: Request):
    skill = await _find_skill(name, request)
    if not skill:
        raise HTTPException(404, "Skill not found.")
    return skill


@router.get("/api/skills/{name}/download")
async def download_skill(name: str, request: Request):
    skill = await _find_skill(name, request)
    if not skill:
        raise HTTPException(404, "Skill not found.")
    return Response(render_skill(skill), media_type="text/markdown; charset=utf-8",
                    headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(skill['name'])}.md"})


# ---------------------------------------------------------------- Skill-Katalog (Unity Catalog, Nutzerrechte)
@router.get("/api/registry")
async def registry_status(request: Request, response: Response):
    response.headers['Cache-Control'] = 'private, no-store'
    email, token = _who(request)
    state = user_state(email)
    cfg = registry.settings()
    if registry.enabled():
        await asyncio.to_thread(catalog_skills, state, token)
    return {"enabled": registry.enabled(), "location": f"{cfg['catalog']}.{cfg['schema']}" if registry.enabled() else "",
            "message": state.catalog_message if registry.enabled() else ""}


@router.post("/api/registry/skills/{name}/publish")
async def publish_skill(name: str, request: Request, response: Response):
    """Publish a personal skill as the next immutable catalog version. Needs MODIFY on the catalog table."""
    response.headers['Cache-Control'] = 'private, no-store'
    email, token = _who(request)
    if not registry.enabled():
        raise HTTPException(404, "The skill catalog is not enabled.")
    state = user_state(email)
    personal = await asyncio.to_thread(load_personal_skills, state, email, token)
    skill = personal.get(name)
    if not skill:
        raise HTTPException(404, "Personal skill not found. Only your own skills can be published.")
    try:
        skill = check_skill(skill["name"], skill["beschreibung"], skill["anleitung"])
        reg = registry.SkillRegistry(_client(token), WAREHOUSE_ID)
        published = await asyncio.to_thread(reg.publish, skill, email)
    except ValueError as e:
        raise HTTPException(400, str(e)) from None
    except registry.RegistryError as e:
        raise HTTPException(409, str(e)) from None
    state.catalog_skills = None
    return {"name": published["name"], "version": published["version"], "owner": published["owner"],
            "unchanged": bool(published.get("unchanged"))}


@router.put("/api/skills/{name}")
async def save_skill(name: str, body: SkillBody, request: Request):
    email, token = _who(request)
    try:
        skill = check_skill(name, body.beschreibung, body.anleitung)
    except ValueError as e:
        raise HTTPException(400, str(e)) from None
    if skill["name"] in team_skills():
        raise HTTPException(400, f"/{skill['name']} is a team skill. Please choose another name.")
    state = user_state(email)
    personal = dict(await asyncio.to_thread(load_personal_skills, state, email, token))
    if skill["name"] not in personal and len(personal) >= MAX_PERSONAL:
        raise HTTPException(400, f"Maximum: {MAX_PERSONAL} personal skills.")
    personal[skill["name"]] = {**skill, "quelle": "persoenlich"}
    await asyncio.to_thread(PersonalSkillStore(_client(token), email).save, personal)
    state.skills = personal
    return {"name": skill["name"], "saved": True}


@router.delete("/api/skills/{name}")
async def delete_skill(name: str, request: Request):
    email, token = _who(request)
    state = user_state(email)
    personal = dict(await asyncio.to_thread(load_personal_skills, state, email, token))
    if name not in personal:
        raise HTTPException(404, "Personal skill not found (team skills can only be edited in the repository).")
    personal.pop(name)
    await asyncio.to_thread(PersonalSkillStore(_client(token), email).save, personal)
    state.skills = personal
    return {"status": "deleted"}


# ---------------------------------------------------------------- Oberfläche
@router.get("/settings", response_class=HTMLResponse)
async def settings_page():
    return HTMLResponse((_STATIC / "settings.html").read_text(encoding="utf-8"))


@router.get("/guide", response_class=HTMLResponse)
async def guide_page():
    return HTMLResponse((_STATIC / "guide.html").read_text(encoding="utf-8"))


@router.get("/static/ui.js")
async def ui_js():
    # Include the running backend's version immediately, without another API request.
    source = 'window.__jiraAppVersion = ' + json.dumps(__version__) + ';\n'
    source += (_STATIC / "ui.js").read_text(encoding="utf-8")
    return Response(source, media_type="application/javascript",
                    headers={"Cache-Control": "no-cache"})


@router.get("/static/img/{name}")
async def guide_image(name: str):
    path = _STATIC / "img" / name
    if not _IMG_RE.fullmatch(name) or not path.is_file():
        raise HTTPException(404, "Image not found.")
    return Response(path.read_bytes(), media_type="image/png", headers={"Cache-Control": "public, max-age=3600"})


def inject_ui(html: bytes) -> bytes:
    if _UI_TAG in html:
        return html
    idx = html.lower().rfind(b"</body>")
    return html[:idx] + _UI_TAG + html[idx:] if idx >= 0 else html + _UI_TAG


def install(app: FastAPI) -> None:
    """Registriert die Routen und fügt ui.js (Zahnrad, Anleitung, Layout) in die HTML-Seiten der Chat-UI ein."""
    from jira_agent.connections import install_connection_lifecycle
    install_connection_lifecycle(app)
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
