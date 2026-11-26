"""Launch the lightweight FastAPI developer app on Windows/macOS/Linux.

Unlike start-app, start-local does not launch MLflow AgentServer, build Node
assets, or ask Databricks for a browser identity. It is loopback-only.
"""
from __future__ import annotations

import os
from pathlib import Path
import sys

from dotenv import load_dotenv


def main() -> None:
    # Run from any working directory; credentials remain in the existing
    # project-root .env and are never written to the browser.
    project_root = Path(__file__).resolve().parents[1]
    load_dotenv(project_root / ".env", override=False)
    if os.environ.get("DATABRICKS_APP_NAME") or os.environ.get("DATABRICKS_RUNTIME_VERSION"):
        raise SystemExit("start-local is disabled inside Databricks Apps. Use start-app there.")

    os.environ["JIRA_AGENT_LOCAL_MODE"] = "1"
    os.environ.setdefault("MLFLOW_TRACKING_URI", "file:" + str(project_root / "mlruns"))
    from agents import set_default_openai_api
    from agents.tracing import set_trace_processors
    set_default_openai_api("chat_completions")
    set_trace_processors([])

    from scripts.build_local_ui import build_local_ui
    assets = build_local_ui()
    print(f"Using shared React UI: {assets}", flush=True)

    import uvicorn

    print("T1 Jira Agent · FastAPI local development")
    print("Open http://127.0.0.1:8000")
    print("Same React UI as Databricks, served by FastAPI; no Node server or Databricks sign-in.")
    print("Local mode is single-user and must not be exposed on a network.")
    uvicorn.run("local_app.server:app", host="127.0.0.1", port=8000, workers=1,
                reload=False, log_level="info")


if __name__ == "__main__":
    main()
