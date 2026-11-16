"""Structured searches keep scope and user text in separate, quoted JQL values."""
import pytest

from jira_agent.adapter import available_tools
from jira_agent.testing import FakeJira, run_tool
from jira_agent.tools import ToolContext


def search(jira, **args):
    return run_tool('jira_search_tickets', jira=jira, **args)


def test_my_open_tickets_keep_project_and_pagination_without_identity_lookup():
    jira = FakeJira(issues={f'ABC-{n}': {'summary': f'Issue {n}'} for n in range(12)})
    result = search(jira, project='abc', assignee='@me', state='open', max_results=10)
    call = jira.calls[-1]
    assert result['total'] == 12 and len(result['issues']) == 10
    assert result['truncated'] and result['next_start_at'] == 10
    assert 'project = "ABC"' in result['query']
    assert 'assignee = currentUser()' in result['query']
    assert 'resolution IS EMPTY' in result['query']
    assert all(path != '/myself' for _, path, _ in jira.calls)
    assert call[2]['jql'] == result['query']
    continuation = search(jira, project='ABC', assignee='@me', state='open', start_at=10)
    assert len(continuation['issues']) == 2 and not continuation['truncated']
    assert jira.calls[-1][2]['startAt'] == 10


def test_example_ticket_does_not_silently_filter_to_current_user():
    jira = FakeJira(issues={'ABC-1': {'summary': 'Example'}})
    result = search(jira, max_results=1)
    assert len(result['issues']) == 1
    assert 'assignee' not in result['query']
    assert jira.calls[-1][2]['maxResults'] == 1


def test_unassigned_resolved_search_uses_actual_status_name():
    result = search(FakeJira(), assignee='@unassigned', state='resolved', status='Funnel')
    assert 'assignee IS EMPTY' in result['query']
    assert 'resolution IS NOT EMPTY' in result['query']
    assert 'status = "Funnel"' in result['query']


def outside_strings(jql):
    """Inspect operators only outside JQL's quoted values, including escaped quotes."""
    inside = escaped = False
    outside = []
    for char in jql:
        if escaped:
            escaped = False
        elif inside and char == '\\':
            escaped = True
        elif char == '"':
            inside = not inside
        elif not inside:
            outside.append(char)
    assert not inside, 'Unclosed JQL string'
    return ''.join(outside)


def test_text_and_status_cannot_add_operators_or_escape_scope():
    jira = FakeJira()
    injected = 'x" OR project = SECRET OR text ~ "*'
    result = search(jira, project='ABC', text=injected, status=injected)
    operators = outside_strings(result['query'])
    assert ' OR ' not in operators and 'SECRET' not in operators
    assert operators.count(' AND ') == 2
    assert 'project = "ABC"' in result['query']
    assert result['query'] == jira.calls[-1][2]['jql']


@pytest.mark.parametrize('args', [
    {'project': 'ABC OR project=SECRET'}, {'assignee': 'x" OR 1=1'},
    {'state': 'invented'}, {'text': 'line\nbreak'}, {'status': 'x\x00y'},
    {'start_at': -1}, {'text': 'x'*256},
])
def test_invalid_filters_do_not_call_jira(args):
    jira = FakeJira()
    assert search(jira, **args)['error'] == 'ValueError'
    assert not jira.calls


def test_punctuation_is_allowed_at_the_text_length_limit_and_results_are_bounded():
    jira = FakeJira()
    assert 'error' not in search(jira, text='*'*255, max_results=999)
    assert jira.calls[-1][2]['maxResults'] == 50


def test_structured_search_is_read_only_and_hidden_until_jira_is_connected():
    assert 'jira_search_tickets' not in {tool.name for tool in available_tools(ToolContext())}
    tool = next(tool for tool in available_tools(ToolContext(jira=FakeJira())) if tool.name == 'jira_search_tickets')
    assert not tool.write
