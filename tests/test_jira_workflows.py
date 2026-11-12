"""Real tool adapter + Jira client + simulated REST: ordinary Jira workflows and failure cases."""
import pytest

from jira_agent.adapter import RunContext, available_tools, build_function_tools, execute
from jira_agent.jira_client import JiraError
from jira_agent.testing import FakeJira, FakeResponse, run_tool
from jira_agent.tools import ToolContext, load_tools


def test_discover_create_assign_and_read_back_ticket():
    jira = FakeJira(issues={'WEST1-9': {}}, users=[{'name': 'v123', 'displayName': 'Test User'}])
    assert run_tool('jira_get_myself', jira=jira)['name'] == 'v123'
    assert run_tool('jira_list_projects', jira=jira)['projects'][0]['key'] == 'WEST1'
    assert run_tool('jira_list_issue_types', jira=jira, project='west1')['issue_types'][0]['name'] == 'Task'
    meta = run_tool('jira_get_create_fields', jira=jira, project='WEST1', issue_type_id='10001')
    assert any(f['id'] == 'summary' and f['required'] for f in meta['fields'])
    args = dict(project='WEST1', summary='Testticket', issue_type='Task', assignee='@me',
                priority='High', components=['Bremse'], labels=['test'], description='Ein Test',
                extra_fields={'customfield_10010': {'id': '42'}})
    before = set(jira.issues)
    pending = run_tool('jira_create_issue', jira=jira, confirm=False, **args)
    assert pending['status'] == 'BESTAETIGUNG_NOETIG'
    assert set(jira.issues) == before
    result = run_tool('jira_create_issue', jira=jira, **args)
    assert result == {'status': 'OK', 'key': 'WEST1-10', 'url': 'https://jira.example/browse/WEST1-10'}
    issue = run_tool('jira_get_issue', jira=jira, issue_key=result['key'])
    assert (issue['summary'], issue['assignee'], issue['description']) == ('Testticket', 'v123', 'Ein Test')
    payload = next(body for method, path, body in jira.calls if path == '/issue' and method == 'POST')['fields']
    assert payload['components'] == [{'name': 'Bremse'}]
    assert payload['customfield_10010'] == {'id': '42'}


def test_existing_issue_workflow_preserves_unspecified_fields():
    jira = FakeJira(issues={'ABC-1': {'description': 'Behalten'}, 'ABC-2': {}})
    assert run_tool('jira_get_edit_fields', jira=jira, issue_key='ABC-1')['fields']
    assert run_tool('jira_update_issue', jira=jira, issue_key='ABC-1',
                    fields={'summary': 'Neuer Titel'}) == {'status': 'OK', 'key': 'ABC-1'}
    assert jira.issues['ABC-1']['description'] == 'Behalten'
    assert run_tool('jira_list_transitions', jira=jira, issue_key='ABC-1')['transitions']
    assert run_tool('jira_set_status', jira=jira, issue_key='ABC-1', status='Erledigt')['status'] == 'OK'
    assert run_tool('jira_set_priority', jira=jira, issue_key='ABC-1', priority='Low')['status'] == 'OK'
    assert run_tool('jira_link_issues', jira=jira, from_key='ABC-1', to_key='ABC-2', link_type='Blocks')['status'] == 'OK'
    assert run_tool('jira_add_worklog', jira=jira, issue_key='ABC-1', time_spent='1h 30m')['status'] == 'OK'
    assert run_tool('jira_assign', jira=jira, issue_key='ABC-1', user_name='@me')['status'] == 'OK'
    assert jira.issues['ABC-1']['status'] == 'Erledigt'
    assert jira.issues['ABC-1']['links'] == [('Blocks', 'ABC-2')]
    assert jira.issues['ABC-1']['worklogs'] == ['1h 30m']
    assert jira.issues['ABC-1']['assignee'] == 'max.muster'


WRITE_CASES = [
    ('jira_create_issue', dict(project='ABC', summary='Test', issue_type='Task')),
    ('jira_update_issue', dict(issue_key='ABC-1', fields={'summary': 'Neu'})),
    ('jira_set_status', dict(issue_key='ABC-1', status='Erledigt')),
    ('jira_set_priority', dict(issue_key='ABC-1', priority='High')),
    ('jira_link_issues', dict(from_key='ABC-1', to_key='ABC-2', link_type='Blocks')),
    ('jira_add_worklog', dict(issue_key='ABC-1', time_spent='1h')),
]


@pytest.mark.parametrize('name,args', WRITE_CASES)
def test_all_new_writes_require_explicit_unchanged_user_approval(name, args):
    jira = FakeJira(issues={'ABC-1': {}, 'ABC-2': {}})
    tool = load_tools()[name]
    ctx = RunContext(ToolContext(jira=jira), b'secret', '')
    pending = execute(tool, ctx, dict(args))
    assert pending['status'] == 'BESTAETIGUNG_NOETIG' and not jira.calls
    code = pending['code']
    ctx.last_user_text = f'Nein, nicht ausführen: {code}'
    assert execute(tool, ctx, {**args, 'confirmation_code': code})['status'] == 'BESTAETIGUNG_NOETIG'
    assert not jira.calls
    other_user = RunContext(ToolContext(jira=jira), b'other-secret', f'ja {code}')
    assert execute(tool, other_user, {**args, 'confirmation_code': code})['status'] == 'BESTAETIGUNG_NOETIG'
    ctx.last_user_text = f'ja {code}'
    changed = {**args, next(iter(args)): 'DIFFERENT'}
    assert execute(tool, ctx, {**changed, 'confirmation_code': code})['status'] == 'BESTAETIGUNG_NOETIG'
    assert not jira.calls
    assert execute(tool, ctx, {**args, 'confirmation_code': code})['status'] == 'OK'
    assert any(method in ('POST', 'PUT') for method, _, _ in jira.calls)


@pytest.mark.parametrize('name,args', [
    ('jira_create_issue', dict(project='../BAD', summary='Test', issue_type='Task')),
    ('jira_create_issue', dict(project='ABC', summary=' ', issue_type='Task')),
    ('jira_create_issue', dict(project='ABC', summary='x'*256, issue_type='Task')),
    ('jira_create_issue', dict(project='ABC', summary='Test', issue_type='Task', extra_fields={'project': {'key':'OTHER'}})),
    ('jira_create_issue', dict(project='ABC', summary='Test', issue_type='Task', assignee='../user')),
    ('jira_update_issue', dict(issue_key='ABC-1', fields={'not_editable': 'x'})),
    ('jira_update_issue', dict(issue_key='ABC-1', fields={'status': {'name': 'Done'}})),
    ('jira_set_status', dict(issue_key='ABC-1', status='Not available')),
    ('jira_link_issues', dict(from_key='ABC-1', to_key='ABC-1', link_type='Blocks')),
    ('jira_add_worklog', dict(issue_key='ABC-1', time_spent='-3h')),
])
def test_invalid_actions_do_not_write(name, args):
    jira = FakeJira(issues={'ABC-1': {}})
    assert 'error' in run_tool(name, jira=jira, **args)
    assert not any(method in ('POST', 'PUT') for method, _, _ in jira.calls)


def test_metadata_pagination_required_custom_fields_and_option_bounds():
    fields = [{'fieldId': f'customfield_{i}', 'name': f'Feld {i}', 'required': True,
               'allowedValues': [{'id': str(n), 'value': str(n)} for n in range(40)]} for i in range(205)]
    jira = FakeJira(create_fields=fields)
    # Client returns every metadata page, including required fields on the last page.
    assert len(jira.create_fields('ABC', '10001')) == 205
    assert [c[2]['startAt'] for c in jira.calls] == [0, 100, 200]
    from jira_agent.tools.jira_metadata import field_summary
    field = field_summary('customfield_0', fields[0])
    assert field['required'] and len(field['allowed_values']) == 30
    assert field['allowed_values_truncated']
    with pytest.raises(ValueError):
        jira.create_fields('ABC', '../10001')


def test_jira_permission_failure_is_reported_without_success(monkeypatch):
    jira = FakeJira()
    monkeypatch.setattr(jira, 'request', lambda *a, **kw: FakeResponse(403, {'errorMessages':['No create permission']}))
    result = run_tool('jira_create_issue', jira=jira, project='ABC', summary='Test', issue_type='Task')
    assert result['error'] == 'JiraError' and 'HTTP 403' in result['details']
    assert 'key' not in result


def test_jira_tools_only_available_when_connected_and_have_sdk_schemas():
    assert not any(t.name.startswith('jira_') for t in available_tools(ToolContext()))
    tools = build_function_tools(ToolContext(jira=FakeJira()))
    create = next(t for t in tools if t.name == 'jira_create_issue')
    assert set(create.params_json_schema['required']) == {'project', 'summary', 'issue_type'}
    assert create.params_json_schema['properties']['extra_fields']['type'] == 'object'
    assert 'confirmation_code' in create.params_json_schema['properties']
    assert run_tool('jira_list_link_types', jira=FakeJira())['link_types'][0]['outward'] == 'blocks'
    assert run_tool('jira_list_priorities', jira=FakeJira())['priorities'][0]['name'] == 'High'
    jira = FakeJira(issues={'ABC-1': {'comments': ['eins','zwei']}})
    assert len(run_tool('jira_get_comments', jira=jira, issue_key='ABC-1', max_results=1)['comments']) == 1


def test_transition_fields_are_discovered_and_passed_without_guessing():
    jira = FakeJira(issues={'ABC-1': {}}, transitions=[
        {'id': '21', 'name': 'Schließen', 'to': 'Erledigt', 'fields': {
            'resolution': {'required': True, 'name': 'Resolution', 'allowedValues': [{'id':'1','name':'Fixed'}]}}}])
    metadata = run_tool('jira_list_transitions', jira=jira, issue_key='ABC-1')
    assert metadata['transitions'][0]['fields'][0]['required']
    result = run_tool('jira_set_status', jira=jira, issue_key='ABC-1', status='Schließen',
                      fields={'resolution': {'id': '1'}})
    assert result['status'] == 'OK'
    assert jira.calls[-1][2]['fields'] == {'resolution': {'id': '1'}}
    jira.calls.clear()
    assert 'error' in run_tool('jira_set_status', jira=jira, issue_key='ABC-1', status='Schließen',
                               fields={'hidden': 'value'})
    assert not any(method == 'POST' for method, _, _ in jira.calls)


def test_tool_selection_for_reusable_read_only_agent():
    names = ['jira_search', 'jira_get_issue']
    assert {t.name for t in available_tools(ToolContext(jira=FakeJira(), enabled_tools=names))} == set(names)
    assert available_tools(ToolContext(jira=FakeJira(), enabled_tools=[])) == []
    assert available_tools(ToolContext(enabled_tools=names)) == []
    with pytest.raises(ValueError, match='Unbekannte Tools'):
        available_tools(ToolContext(enabled_tools=['missing_tool']))
    with pytest.raises(ValueError, match='Liste'):
        available_tools(ToolContext(enabled_tools='jira_search'))


def test_field_value_search_and_pagination_support_large_projects():
    fields = [{'fieldId': 'customfield_123', 'name': 'Team', 'required': True,
               'allowedValues': [{'id': str(n), 'value': f'Team {n}'} for n in range(80)]}]
    jira = FakeJira(create_fields=fields)
    overview = run_tool('jira_get_create_fields', jira=jira, project='ABC', issue_type_id='10001')
    assert overview['fields'][0]['allowed_values_total'] == 80
    assert 'allowed_values' not in overview['fields'][0]
    second = run_tool('jira_get_create_fields', jira=jira, project='ABC', issue_type_id='10001',
                      field_id='customfield_123', value_offset=30)['fields'][0]
    assert second['allowed_values'][0]['id'] == '30'
    assert second['allowed_values_truncated']
    found = run_tool('jira_get_create_fields', jira=jira, project='ABC', issue_type_id='10001',
                     field_id='customfield_123', value_query='Team 79')['fields'][0]
    assert found['allowed_values'] == [{'id': '79', 'value': 'Team 79'}]


def test_large_tool_result_remains_valid_json():
    import asyncio
    import json
    from types import SimpleNamespace
    from jira_agent.adapter import _on_invoke
    from jira_agent.tools import Tool

    large = Tool('test_large', 'Test', {}, (), lambda ctx: {'rows': ['x'*500]*100})
    ctx = SimpleNamespace(context=RunContext(ToolContext(), b'secret', ''))
    result = json.loads(asyncio.run(_on_invoke(large, ctx, '{}')))
    assert result['status'] == 'RESULT_TOO_LARGE' and result['truncated']


def test_metadata_respects_server_page_size(monkeypatch):
    jira = FakeJira()
    starts = []
    def request(method, path, **kw):
        start = kw['params']['startAt']
        starts.append(start)
        return FakeResponse(200, {'values': [{'id':str(n)} for n in range(start, min(start+2,5))],
                                  'isLast':start+2 >= 5})
    monkeypatch.setattr(jira,'request',request)
    assert len(jira.project_issue_types('ABC')) == 5
    assert starts == [0,2,4]


def test_ambiguous_transition_requires_specific_id():
    jira = FakeJira(issues={'ABC-1': {}}, transitions=[
        {'id':'11','name':'Schließen','to':'Erledigt'},
        {'id':'21','name':'Verwerfen','to':'Erledigt'}])
    result = run_tool('jira_set_status', jira=jira, issue_key='ABC-1', status='Erledigt')
    assert result['error'] == 'JiraError' and 'Mehrere' in result['details']
    assert not any(method == 'POST' for method,_,_ in jira.calls)
    assert run_tool('jira_set_status', jira=jira, issue_key='ABC-1', status='11')['status'] == 'OK'


def test_runtime_builds_agent_with_selected_tools_and_user_context(monkeypatch):
    import jira_agent.runtime as runtime
    from jira_agent.state import UserState

    jira = FakeJira(users=[{'name':'jira.user','displayName':'Jira User'}])
    state = UserState(creds={'jira_token':'test-only'}, jira_user='jira.user',
                      settings=dict(runtime.DEFAULT_SETTINGS), skills={})
    monkeypatch.setattr(runtime, 'user_state', lambda email: state)
    monkeypatch.setattr(runtime, 'JiraClient', lambda *a: jira)
    monkeypatch.setattr(runtime, 'build_model', lambda *a: 'test-model')
    monkeypatch.setitem(runtime.CFG['agent'], 'enabled_tools', ['jira_create_issue','jira_get_myself'])
    agent, context = runtime.prepare({'x-forwarded-email':'runtime@example.test'}, [])
    assert {t.name for t in agent.tools} == {'jira_create_issue','jira_get_myself'}
    assert context.tool_ctx.jira is jira
    assert 'verbunden als jira.user' in agent.instructions
    assert 'Tatsächlich verfügbare Tools: jira_create_issue, jira_get_myself' in agent.instructions
