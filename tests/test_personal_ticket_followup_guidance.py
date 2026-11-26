"""Regression: generic follow-ups stay scoped to the user's own Jira tickets."""
from jira_agent.runtime import JIRA_GUIDANCE, capability_guidance


def test_breakdown_followup_keeps_personal_ticket_scope():
    assert 'when the previous user request or verified Jira result concerns' in JIRA_GUIDANCE
    assert 'personal tickets, not all tickets in Jira' in JIRA_GUIDANCE
    assert 'assignee=currentUser()' in JIRA_GUIDANCE
    assert '"Breakdown" alone NEVER means' in JIRA_GUIDANCE
    assert 'ONLY when the user explicitly asks' in JIRA_GUIDANCE


def test_prioritization_requires_all_pages_and_honest_effort():
    assert 'next_start_at until the known Jira total is covered' in JIRA_GUIDANCE
    assert 'Do not silently rank only the first 10' in JIRA_GUIDANCE
    assert 'never manufacture effort estimates' in JIRA_GUIDANCE
    assert 'mark it unknown' in JIRA_GUIDANCE


def test_guidance_applies_only_to_jira_enabled_agents():
    assert 'Breakdown' in capability_guidance({'jira_search_tickets'})
    assert 'Breakdown' not in capability_guidance({'run_readonly_sql'})
