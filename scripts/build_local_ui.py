"""Build the exact Databricks React chat client once for standalone FastAPI.

The checked-in patch functions remain the single source for custom Jira UI
behavior. The compiled JS/CSS is local build output, not duplicated source.
No npm command is run once the client/dist index exists.
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import tempfile
from pathlib import Path

from scripts.frontend_source import FRONTEND_REVISION, prepare_frontend

ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "e2e-chatbot-app-next"
DIST = FRONTEND / "client" / "dist"


def _run(argv: list[str], *, cwd: Path | None = None) -> None:
    subprocess.run(argv, cwd=cwd, check=True)


def _npm() -> str:
    value = shutil.which("npm")
    if value is None:
        raise RuntimeError(
            "The React UI must be built once. Install Node.js 22+ with npm, "
            "then run uv run start-local. Regular starts do not need Node.")
    return value


def ensure_frontend() -> None:
    if FRONTEND.is_dir():
        return
    print("Downloading pinned Databricks React UI (first build only)...", flush=True)
    with tempfile.TemporaryDirectory(prefix="jira-frontend-", dir=ROOT) as tmp:
        checkout = Path(tmp) / "app-templates"
        _run(["git", "clone", "--filter=blob:none", "--sparse",
              "https://github.com/databricks/app-templates.git", str(checkout)])
        _run(["git", "checkout", "--detach", FRONTEND_REVISION], cwd=checkout)
        _run(["git", "sparse-checkout", "set", "e2e-chatbot-app-next"], cwd=checkout)
        (checkout / "e2e-chatbot-app-next").rename(FRONTEND)


def build_local_ui(*, force: bool = False) -> Path:
    if (DIST / "index.html").is_file() and not force:
        return DIST
    npm = _npm()
    ensure_frontend()
    prepare_frontend(FRONTEND)
    if not (FRONTEND / "node_modules").is_dir():
        print("Installing React build dependencies (one-time)...", flush=True)
        _run([npm, "ci"], cwd=FRONTEND)
    print("Building the same React interface used on Databricks...", flush=True)
    # Build only the browser bundle. Never launch the Node backend, DB migrations
    # or Databricks authentication flow for the local FastAPI runtime.
    _run([npm, "run", "build:client"], cwd=FRONTEND)
    if not (DIST / "index.html").is_file():
        raise RuntimeError("The React build finished without client/dist/index.html")
    return DIST


def main() -> None:
    p = argparse.ArgumentParser(description="Build the shared React UI for FastAPI")
    p.add_argument("--force", action="store_true", help="Force a fresh browser build")
    args = p.parse_args()
    print("Built at:", build_local_ui(force=args.force))


if __name__ == "__main__":
    main()
