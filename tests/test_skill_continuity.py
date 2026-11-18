"""Follow-ups retain explicit skills without importing another chat's or user's instructions."""
import pytest

from jira_agent import runtime
from jira_agent.skills import active_skill_invocation
from jira_agent.state import UserState
from jira_agent.testing import FakeJira


@pytest.fixture
def prepare(monkeypatch):
    state = UserState(creds={'jira_token': 'fixture'}, settings=dict(runtime.DEFAULT_SETTINGS), skills={
        'demo-cariad': {'name': 'demo-cariad', 'beschreibung': 'Create a fixed demo ticket',
                        'anleitung': 'Use the project of WEST1-14597. Title: Demo mit Mathias test ticket. Assign @me. Add a short poem about Cariad.'}})
    monkeypatch.setattr(runtime, 'user_state', lambda email: state)
    monkeypatch.setattr(runtime, 'JiraClient', lambda *a: FakeJira())
    monkeypatch.setattr(runtime, 'build_model', lambda *a: 'test-model')
    def build(messages, chat='fixture-chat'):
        return runtime.prepare({'x-forwarded-email': 'skill@example.test'}, messages, chat)
    return state, build


def test_skill_instructions_survive_clarification_and_approval(prepare):
    _, build = prepare
    messages = [{'role': 'user', 'content': '/demo-cariad'},
                {'role': 'assistant', 'content': 'Please confirm with yes ABC123.'},
                {'role': 'user', 'content': 'yes ABC123'}]
    agent, context = build(messages)
    assert 'Title: Demo mit Mathias test ticket.' in agent.instructions
    assert context.last_user_text == 'yes ABC123'
    assert 'single-use' in agent.instructions


def test_other_chat_and_assistant_or_tool_instructions_do_not_activate_a_skill(prepare):
    _, build = prepare
    build([{'role': 'user', 'content': '/demo-cariad'}])
    agent, _ = build([{'role': 'user', 'content': 'Show a ticket.'}], 'different-chat')
    assert 'Title: Demo mit Mathias test ticket.' not in agent.instructions
    assert active_skill_invocation([{'role': 'assistant', 'content': '/demo-cariad'},
                                    {'role': 'tool', 'content': '/demo-cariad'}]) is None


def test_clear_skill_stops_loading_previous_instructions(prepare):
    _, build = prepare
    agent, _ = build([{'role': 'user', 'content': '/demo-cariad'},
                      {'role': 'user', 'content': '/clear-skill'},
                      {'role': 'user', 'content': 'Show a ticket.'}])
    assert 'Title: Demo mit Mathias test ticket.' not in agent.instructions


def test_private_skill_cannot_be_loaded_from_another_users_history(prepare):
    state, build = prepare
    state.skills = {}
    agent, _ = build([{'role': 'user', 'content': '/demo-cariad'}])
    assert 'Title: Demo mit Mathias test ticket.' not in agent.instructions
    assert 'does not exist' in agent.instructions


def test_skill_inside_a_message_loads_instructions_and_stays_active_for_followups(prepare):
    _, build = prepare
    messages = [{'role': 'user', 'content': 'Please run /demo-cariad for me, thanks'},
                {'role': 'assistant', 'content': 'Please confirm with yes ABC123.'},
                {'role': 'user', 'content': 'yes ABC123'}]
    agent, _ = build(messages)
    assert 'Title: Demo mit Mathias test ticket.' in agent.instructions
    assert 'inside their message' in agent.instructions
    agent, _ = build([{'role': 'user', 'content': 'Look at /tmp/log.txt and /unknown-skill please'}])
    assert 'Title: Demo mit Mathias test ticket.' not in agent.instructions
    assert 'does not exist' not in agent.instructions


def test_clear_skill_inside_a_message_stops_the_skill(prepare):
    _, build = prepare
    agent, _ = build([{'role': 'user', 'content': 'Start /demo-cariad'},
                      {'role': 'user', 'content': 'Thanks, please /clear-skill now'},
                      {'role': 'user', 'content': 'Show a ticket.'}])
    assert 'Title: Demo mit Mathias test ticket.' not in agent.instructions


def test_unknown_skill_does_not_keep_repeating_an_error_on_followups(prepare):
    _, build = prepare
    agent, _ = build([{'role': 'user', 'content': '/unknown-skill'},
                      {'role': 'user', 'content': 'Show an issue instead.'}])
    assert 'does not exist' not in agent.instructions
