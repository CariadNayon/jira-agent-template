"""Deploy der App mit einem Befehl: uv run deploy

Prüft das Bundle (databricks.yml), lädt den Code hoch und startet die App neu. App-Name, Secret und
Warehouse stehen als Standardwerte in databricks.yml (variables) und lassen sich mit --var überschreiben.

    uv run deploy                              # Ziel "dev", Profil aus .env (DATABRICKS_CONFIG_PROFILE)
    uv run deploy --profile nayon              # anderes CLI-Profil
    uv run deploy --check                      # nur prüfen, nichts hochladen
    uv run deploy --bind                       # bestehende App gleichen Namens übernehmen (einmalig)
    uv run deploy --var app_name=agent-test    # Wert aus databricks.yml überschreiben
    uv run deploy --target prod                # Produktion (z. B. in GitHub Actions)
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
APP_KEY = "agent_openai_agents_sdk"  # Ressourcen-Schlüssel in databricks.yml


def profile_from_env_file() -> str | None:
    env_file = ROOT / ".env"
    if not env_file.exists():
        return None
    for line in env_file.read_text(encoding="utf-8").splitlines():
        key, _, value = line.partition("=")
        if key.strip() == "DATABRICKS_CONFIG_PROFILE" and value.strip():
            return value.strip().strip('"').strip("'")
    return None


def run(cmd: list[str], env: dict) -> subprocess.CompletedProcess:
    print("\n> " + " ".join(cmd), flush=True)
    return subprocess.run(cmd, cwd=ROOT, env=env, text=True)


def main() -> None:
    p = argparse.ArgumentParser(description="App deployen (Werte aus databricks.yml).")
    p.add_argument("--target", default="dev", help="Bundle-Ziel aus databricks.yml (dev oder prod)")
    p.add_argument("--profile", help="Databricks-CLI-Profil (Standard: DATABRICKS_CONFIG_PROFILE aus .env)")
    p.add_argument("--var", action="append", default=[], metavar="NAME=WERT",
                   help="Variable aus databricks.yml überschreiben (mehrfach möglich)")
    p.add_argument("--check", action="store_true", help="nur prüfen (bundle validate)")
    p.add_argument("--bind", action="store_true", help="bestehende App gleichen Namens an das Bundle binden")
    p.add_argument("--no-start", action="store_true", help="nur hochladen, App nicht neu starten")
    args = p.parse_args()

    if not shutil.which("databricks"):
        sys.exit("Databricks CLI fehlt: https://docs.databricks.com/aws/en/dev-tools/cli/install")

    sys.path.insert(0, str(ROOT))
    from jira_agent import BUNDLE

    overrides = dict(v.split("=", 1) for v in args.var)
    app_name = overrides.get("app_name", BUNDLE.get("app_name", ""))
    common = ["--target", args.target, *[f"--var={k}={v}" for k, v in overrides.items()]]

    env = dict(os.environ)
    profile = args.profile or os.environ.get("DATABRICKS_CONFIG_PROFILE") or profile_from_env_file()
    if profile:
        env["DATABRICKS_CONFIG_PROFILE"] = profile
    elif not os.environ.get("DATABRICKS_HOST"):
        print("Hinweis: kein Profil gefunden (.env fehlt) – mit --profile <name> angeben oder 'uv run quickstart'.")
    print(f"App: {app_name} | Ziel: {args.target} | Profil: {profile or '(Standard)'}")

    if run(["databricks", "bundle", "validate", *common], env).returncode != 0:
        sys.exit("Prüfung fehlgeschlagen – siehe Meldung oben. Angemeldet? databricks auth login --profile <name>")
    if args.check:
        print("\nPrüfung OK.")
        return

    if args.bind:
        if run(["databricks", "bundle", "deployment", "bind", APP_KEY, app_name, "--auto-approve", *common],
               env).returncode != 0:
            sys.exit("Binden fehlgeschlagen – siehe Meldung oben.")

    if run(["databricks", "bundle", "deploy", *common], env).returncode != 0:
        sys.exit("Deploy fehlgeschlagen. Bei 'An app with the same name already exists': "
                 "uv run deploy --bind (übernimmt die bestehende App) – oder app_name in databricks.yml ändern.")

    if not args.no_start:
        if run(["databricks", "bundle", "run", APP_KEY, *common], env).returncode != 0:
            sys.exit(f"Start fehlgeschlagen. Logs: databricks apps logs {app_name}")

    info = subprocess.run(["databricks", "apps", "get", app_name, "-o", "json"],
                          cwd=ROOT, env=env, text=True, capture_output=True)
    url = json.loads(info.stdout).get("url") if info.returncode == 0 else None
    print(f"\nFertig. App: {url or app_name}")


if __name__ == "__main__":
    main()
