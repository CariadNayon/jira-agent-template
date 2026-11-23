"""In-app guide points to the approved internal source repository."""
from pathlib import Path


def test_guide_uses_internal_vw_clone_url():
    guide = (Path(__file__).resolve().parents[1] / "jira_agent/static/guide.html").read_text(encoding="utf-8")
    assert "https://git.hub.vwgroup.com/v8ee318/jira_agent_template.git" in guide
    assert "https://github.com/CariadNayon/jira-agent-template.git" not in guide
    assert "permission to read the repository" in guide
