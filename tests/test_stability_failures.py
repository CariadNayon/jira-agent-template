"""Real adapter/client paths: rejected changes can be corrected; uncertain writes stay consumed."""
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
import requests

from jira_agent.adapter import RunContext, execute
from jira_agent.jira_client import JiraClient
from jira_agent.testing import FakeJira, FakeResponse
from jira_agent.tools import Tool, ToolContext, load_tools
from jira_agent.write_outcome import InputValidationError

ARGS = {'issue_key': 'ABC-1', 'fields': {'summary': 'Updated'}}


def approve(rc, tool, args):
    rc.last_user_text = 'Please update the issue.'
    code = execute(tool, rc, args)['code']
    rc.last_user_text = 'yes ' + code
    return code, execute(tool, rc, {**args, 'confirmation_code': code})


@pytest.mark.parametrize('status', [400, 401, 403, 404, 405, 409, 422, 429])
def test_rejected_write_does_not_lock_out_a_new_explicit_attempt(status):
    jira = FakeJira(issues={'ABC-1': {}})
    request = jira.request
    rejected = [True]
    attempts = []
    def respond(method, path, **kw):
        if method == 'PUT':
            attempts.append(1)
            if rejected[0]:
                return FakeResponse(status, {'errorMessages': ['Rejected by fixture']})
        return request(method, path, **kw)
    jira.request = respond
    rc = RunContext(ToolContext(jira=jira), b'fixture', '')
    tool = load_tools()['jira_update_issue']
    code, failed = approve(rc, tool, ARGS)
    assert failed['outcome'] == 'not_executed' and failed['status_code'] == status
    assert jira.issues['ABC-1']['summary'] == ''
    replay = execute(tool, rc, {**ARGS, 'confirmation_code': code})
    assert replay['receipt_replayed'] and replay['outcome'] == 'not_executed'
    assert len(attempts) == 1
    rejected[0] = False
    new_code, result = approve(rc, tool, ARGS)
    assert new_code != code and result['status'] == 'OK'
    assert jira.issues['ABC-1']['summary'] == 'Updated' and len(attempts) == 2
    rc.last_user_text = 'yes ' + code
    assert execute(tool, rc, {**ARGS, 'confirmation_code': code})['outcome'] == 'not_executed'
    assert len(attempts) == 2


@pytest.mark.parametrize('failure', [408, 500, 503, 'lost_response'])
def test_ambiguous_mutation_is_not_reissued(failure):
    jira = FakeJira(issues={'ABC-1': {}})
    original = jira.request
    attempts = []
    def respond(method, path, **kw):
        if method == 'PUT':
            attempts.append(1)
            if failure == 'lost_response':
                original(method, path, **kw)
                raise requests.ReadTimeout('Response lost after applying fixture mutation')
            return FakeResponse(failure, {'errorMessages': ['Temporary failure']})
        return original(method, path, **kw)
    jira.request = respond
    rc = RunContext(ToolContext(jira=jira), b'fixture', '')
    tool = load_tools()['jira_update_issue']
    code, failed = approve(rc, tool, ARGS)
    assert failed['outcome'] == 'unverified'
    for args in (ARGS, {**ARGS, 'confirmation_code': code}):
        assert execute(tool, rc, args)['outcome'] == 'unverified'
    assert len(attempts) == 1


def test_validation_and_metadata_rejection_before_write_are_known_no_change():
    jira = FakeJira(issues={'ABC-1': {}})
    rc = RunContext(ToolContext(jira=jira), b'fixture', '')
    tool = load_tools()['jira_update_issue']
    _, result = approve(rc, tool, {'issue_key': 'ABC-1', 'fields': {'unknown_field': 'value'}})
    assert result['outcome'] == 'not_executed'
    assert not any(method == 'PUT' for method, _, _ in jira.calls)
    jira.request = lambda *a, **kw: FakeResponse(403, {'errorMessages': ['No edit metadata access']})
    _, result = approve(rc, tool, ARGS)
    assert result['outcome'] == 'not_executed'


def test_a_later_validation_error_cannot_hide_an_already_applied_change():
    jira = FakeJira(issues={'ABC-1': {}})
    def combined(ctx):
        ctx.jira.update_fields('ABC-1', summary='Applied')
        JiraClient.check_text('', 'Next summary', 255)
    tool = Tool('combined_fixture', 'Test', {}, (), combined, write=True)
    _, result = approve(RunContext(ToolContext(jira=jira), b'fixture', ''), tool, {})
    assert jira.issues['ABC-1']['summary'] == 'Applied'
    assert result['outcome'] == 'unverified'


def test_mutation_observations_are_isolated_across_concurrent_tools():
    barrier = Barrier(2)
    def combined(ctx, valid):
        barrier.wait(timeout=5)
        if not valid:
            raise InputValidationError('Fixture input rejected')
        ctx.jira.update_fields('ABC-1', summary='Applied')
        return {'status': 'OK'}
    tool = Tool('parallel_fixture', 'Test', {}, (), combined, write=True)
    def run(valid):
        rc = RunContext(ToolContext(jira=FakeJira(issues={'ABC-1': {}})), b'fixture', '')
        return approve(rc, tool, {'valid': valid})[1]
    with ThreadPoolExecutor(max_workers=2) as pool:
        good = pool.submit(run, True)
        bad = pool.submit(run, False)
        assert good.result()['status'] == 'OK'
        assert bad.result()['outcome'] == 'not_executed'


@pytest.mark.parametrize('field,value', [('project', {'key': 'ABC'}), ('labels', 'demo'),
    ('components', 'Component'), ('extra_fields', ['bad']), ('assignee', {'name': 'user'}),
    ('description', {'text': 'bad'})])
def test_malformed_model_arguments_fail_before_creating_an_issue(field, value):
    jira = FakeJira()
    args = {'project': 'ABC', 'summary': 'Fixture', 'issue_type': 'Task', field: value}
    rc = RunContext(ToolContext(jira=jira), b'fixture', '')
    _, result = approve(rc, load_tools()['jira_create_issue'], args)
    assert result['outcome'] == 'not_executed' and result['error'] == 'ValueError'
    assert not jira.calls and not jira.issues
