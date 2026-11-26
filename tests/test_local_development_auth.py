"""Regression tests for explicit, localhost-scoped authentication.

No Databricks Apps session is replaced unless the launcher opts into local mode.
"""
from pathlib import Path
from unittest.mock import patch

import pytest

from jira_agent.runtime import identity, local_mode_active
from scripts.frontend_local_auth import ensure_frontend_local_auth


def test_local_identity_is_explicit_and_ignores_spoofed_headers(monkeypatch):
    monkeypatch.setenv("JIRA_AGENT_LOCAL_MODE", "1")
    monkeypatch.delenv("DATABRICKS_APP_NAME", raising=False)
    monkeypatch.delenv("DATABRICKS_RUNTIME_VERSION", raising=False)
    assert local_mode_active()
    assert identity({"X-Forwarded-Email": "someone@company.test",
                     "X-Forwarded-Access-Token": "forged"}) == ("local", None)


@pytest.mark.parametrize("marker", ["DATABRICKS_APP_NAME", "DATABRICKS_RUNTIME_VERSION"])
def test_hosted_app_never_uses_local_identity(monkeypatch, marker):
    monkeypatch.setenv("JIRA_AGENT_LOCAL_MODE", "1")
    monkeypatch.setenv(marker, "hosted")
    assert not local_mode_active()
    assert identity({"X-Forwarded-Email": "real@company.test",
                     "X-Forwarded-Access-Token": "obo-token"}) == (
                         "real@company.test", "obo-token")


def test_regular_launch_keeps_hosted_identity(monkeypatch):
    monkeypatch.delenv("JIRA_AGENT_LOCAL_MODE", raising=False)
    assert not local_mode_active()
    assert identity({"X-Forwarded-Email": "real@company.test"}) == (
        "real@company.test", None)


def test_pinned_frontend_is_patched_idempotently(tmp_path):
    auth = tmp_path / "server/src/middleware/auth.ts"
    provider = tmp_path / "packages/ai-sdk-providers/src/providers-server.ts"
    index = tmp_path / "server/src/index.ts"
    for path in (auth, provider, index):
        path.parent.mkdir(parents=True, exist_ok=True)
    auth.write_text("  try {\n    const session = await getAuthSession({", encoding="utf-8")
    provider.write_text(
        "  console.log('Creating new OAuth provider');\n"
        "  // Ensure we have a valid token before creating provider", encoding="utf-8")
    index.write_text("  app.listen(PORT, () => {", encoding="utf-8")

    ensure_frontend_local_auth(tmp_path)
    first = tuple(path.read_text(encoding="utf-8") for path in (auth, provider, index))
    ensure_frontend_local_auth(tmp_path)
    second = tuple(path.read_text(encoding="utf-8") for path in (auth, provider, index))
    assert first == second
    assert "JIRA_AGENT_LOCAL_MODE === '1'" in first[0]
    assert "req.session" in first[0]
    assert "localProvider" in first[1]
    assert "getProviderToken" not in first[1].split("return localProvider;")[0]
    assert "'127.0.0.1'" in first[2]


def test_frontend_patch_fails_closed_when_upstream_changes(tmp_path):
    for name in ("server/src/middleware/auth.ts",
                 "packages/ai-sdk-providers/src/providers-server.ts",
                 "server/src/index.ts"):
        p = tmp_path / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("unknown upstream", encoding="utf-8")
    with pytest.raises(RuntimeError, match="required anchor missing"):
        ensure_frontend_local_auth(tmp_path)
