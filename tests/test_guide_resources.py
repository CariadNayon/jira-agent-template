"""Guide and bundle agree about the app's deployed resource bindings and rights."""
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_onboarding_lists_all_required_resources_and_optional_fifth():
    guide = (ROOT / "jira_agent/static/guide.html").read_text(encoding="utf-8")
    section = guide.split('id="zugriffe"', 1)[1].split('id="bereitstellen"', 1)[0]
    for name in ("secret", "sql-warehouse", "experiment", "jira-token-key", "secret-2"):
        assert f"<code>{name}</code>" in section
    for scope in ("sql", "catalog.catalogs:read", "catalog.schemas:read",
                  "catalog.tables:read", "workspace.workspace"):
        assert scope in section
    assert "CAN_EDIT" in section
    assert "Post-deployment smoke test" in guide
    assert "Break down my open tickets" in guide


def test_bundle_matches_running_app_mlflow_permission():
    bundle = (ROOT / "databricks.yml").read_text(encoding="utf-8")
    assert "permission: 'CAN_EDIT'" in bundle
    assert "permission: 'CAN_MANAGE'" not in bundle
    app = (ROOT / "app.yaml").read_text(encoding="utf-8")
    for binding in ("secret", "sql-warehouse", "experiment", "jira-token-key"):
        assert binding in app
