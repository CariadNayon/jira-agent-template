"""Local FastAPI runtime for the SAME React UI as the hosted Databricks app.

The React bundle is built once via scripts/build_local_ui.py and served as
static files. The Python API provides chat transport and the existing /jira/*
settings/tools. No Node server, MLflow AgentServer or Databricks browser auth.
This unauthenticated development server must remain on 127.0.0.1.
"""
from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response

from jira_agent.connections import close_connections
from jira_agent.web import inject_ui, router as jira_router
from local_app.react_api import router as react_router

DIST = Path(__file__).resolve().parents[1] / "e2e-chatbot-app-next" / "client" / "dist"

app = FastAPI(title="T1 Jira Agent - Local React Dev", docs_url=None, redoc_url=None)
app.add_middleware(TrustedHostMiddleware, allowed_hosts=["localhost", "127.0.0.1"])
app.include_router(jira_router)
app.include_router(react_router)


@app.middleware("http")
async def local_security(request: Request, call_next):
    # CSRF boundary for an unauthenticated loopback-only developer server.
    # Cross-site JavaScript requests include Origin; non-JSON form submissions
    # cannot mutate settings, Jira credentials or issue tickets.
    if request.method not in ("GET", "HEAD", "OPTIONS"):
        origin = request.headers.get("origin")
        if origin and origin not in ("http://127.0.0.1:8000", "http://localhost:8000"):
            return JSONResponse({"detail": "Cross-origin requests are blocked."}, status_code=403)
        media = request.headers.get("content-type", "").split(";")[0].strip().lower()
        # The hosted Jira toolbar uploads raw attachments via POST.
        upload = request.url.path == "/jira/api/upload"
        if not (media == "application/json" or upload or
                (request.method == "DELETE" and not media)):
            return JSONResponse({"detail": "Unsupported content type."}, status_code=415)
    return await call_next(request)


@app.on_event("shutdown")
async def shutdown():
    await close_connections()


def _react_html() -> HTMLResponse:
    index = DIST / "index.html"
    if not index.is_file():
        raise HTTPException(503, "React UI missing. Run uv run build-local-ui.")
    # Preserve the custom Jira brand/header, guide, settings, skills,
    # upload controls and confirmation buttons from the hosted app.
    html = inject_ui(index.read_bytes()).decode("utf-8")
    return HTMLResponse(html, headers={
        "Cache-Control": "no-store",
        "Content-Security-Policy":
            "img-src 'self' data: blob:; object-src 'none'; frame-ancestors 'none'",
    })


@app.get("/")
async def homepage():
    return _react_html()


@app.get("/health")
async def health():
    return {"status": "ok", "mode": "local-fastapi", "ui": "shared-react"}


@app.get("/assets/{filename:path}")
async def react_asset(filename: str):
    directory = (DIST / "assets").resolve()
    path = (directory / filename).resolve()
    if not path.is_relative_to(directory) or not path.is_file():
        raise HTTPException(404, "Asset not found")
    return FileResponse(path, headers={"Cache-Control": "public, max-age=86400"})


@app.get("/chat/{conversation_id}")
async def react_chat_page(conversation_id: str):
    return _react_html()


@app.get("/{filename:path}")
async def react_static_or_route(filename: str):
    # Serve Vite's public assets, then fall back to React Router. Keep the
    # existing /jira and /api routes above this catch-all.
    root = DIST.resolve()
    candidate = (root / filename).resolve()
    if candidate.is_relative_to(root) and candidate.is_file():
        return FileResponse(candidate)
    return _react_html()
