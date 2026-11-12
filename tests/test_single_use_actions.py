"""Regression tests for duplicates across model calls, requests, and threads."""
from concurrent.futures import ThreadPoolExecutor
from threading import Event

from jira_agent.adapter import RunContext, execute
from jira_agent.approvals import ActionLedger
from jira_agent.testing import FakeJira
from jira_agent.tools import Tool, ToolContext, load_tools

ARGS = {'project': 'ABC', 'summary': 'Test', 'issue_type': 'Task'}


def context(ledger, message='', chat='chat-1', secret=b'secret'):
    return RunContext(ToolContext(jira=FakeJira()), secret, message,
                      actions=ledger, conversation_id=chat)


def test_same_approval_across_requests_creates_one_ticket_and_returns_receipt():
    ledger = ActionLedger()
    jira = FakeJira()
    t = load_tools()['jira_create_issue']
    first = context(ledger)
    code = execute(t, first, ARGS)['code']
    for number in range(3):
        rc = context(ledger, f'ja {code}')
        rc.tool_ctx.jira = jira
        result = execute(t, rc, {**ARGS, 'confirmation_code': code})
        assert result['key'] == 'ABC-1'
        assert result.get('already_executed', False) == (number > 0)
    assert len(jira.issues) == 1


def test_intentional_repeat_needs_new_proposal_and_new_confirmation():
    ledger = ActionLedger()
    rc = context(ledger)
    t = load_tools()['jira_create_issue']
    old = execute(t, rc, ARGS)['code']
    rc.last_user_text = f'ja {old}'
    execute(t, rc, {**ARGS, 'confirmation_code': old})
    rc.last_user_text = 'Erstelle absichtlich noch ein identisches Ticket.'
    new = execute(t, rc, ARGS)['code']
    assert new != old and len(rc.tool_ctx.jira.issues) == 1
    rc.last_user_text = f'ja {new}'
    assert execute(t, rc, {**ARGS, 'confirmation_code': new})['key'] == 'ABC-2'


def test_approval_expires_and_cannot_be_reused_for_another_chat_or_user():
    now = [0.0]
    ledger = ActionLedger(clock=lambda: now[0])
    rc = context(ledger)
    t = load_tools()['jira_create_issue']
    code = execute(t, rc, ARGS)['code']
    for other in [context(ledger, f'ja {code}', chat='other-chat'),
                  context(ActionLedger(), f'ja {code}'),
                  context(ledger, f'ja {code}', secret=b'other-user')]:
        assert execute(t, other, {**ARGS, 'confirmation_code': code})['status'] == 'BESTAETIGUNG_NOETIG'
        assert not other.tool_ctx.jira.issues
    now[0] = 601
    rc.last_user_text = f'ja {code}'
    pending = execute(t, rc, {**ARGS, 'confirmation_code': code})
    assert pending['status'] == 'BESTAETIGUNG_NOETIG' and pending['code'] != code
    assert not rc.tool_ctx.jira.issues


def test_concurrent_retries_cannot_pass_the_same_approval():
    ledger = ActionLedger()
    entered, release = Event(), Event()
    calls = []
    def write(ctx):
        calls.append('write')
        entered.set()
        assert release.wait(5)
        return {'status': 'OK', 'key': 'ABC-1'}
    t = Tool('slow_create', 'Test', {}, (), write, write=True)
    code = execute(t, context(ledger), {})['code']
    with ThreadPoolExecutor(max_workers=2) as pool:
        running = pool.submit(execute, t, context(ledger, f'ja {code}'), {'confirmation_code': code})
        assert entered.wait(5)
        duplicate = execute(t, context(ledger, f'ja {code}'), {'confirmation_code': code})
        assert duplicate['status'] == 'AKTION_LAEUFT'
        # Omitting the code while the original is in progress cannot obtain a second approval.
        assert execute(t, context(ledger, 'Nochmals'), {})['status'] == 'AKTION_LAEUFT'
        release.set()
        assert running.result()['status'] == 'OK'
    assert calls == ['write']


def test_uncertain_timeout_is_not_retried_even_without_confirmation_code():
    ledger = ActionLedger()
    calls = []
    def uncertain(ctx):
        calls.append('remote-write')
        raise TimeoutError('Response was lost after the remote write')
    t = Tool('uncertain_create', 'Test', {}, (), uncertain, write=True)
    code = execute(t, context(ledger), {})['code']
    for args in [{'confirmation_code': code}, {'confirmation_code': code}, {}]:
        result = execute(t, context(ledger, f'ja {code}'), args)
        assert result['outcome'] == 'unverified'
    assert calls == ['remote-write']


def test_completed_write_is_not_reissued_when_fallback_model_omits_code():
    ledger = ActionLedger()
    rc = context(ledger)
    t = load_tools()['jira_create_issue']
    code = execute(t, rc, ARGS)['code']
    rc.last_user_text = f'ja {code}'
    execute(t, rc, {**ARGS, 'confirmation_code': code})
    result = execute(t, rc, ARGS)
    assert result['already_executed'] and len(rc.tool_ctx.jira.issues) == 1


def test_ledger_capacity_does_not_evict_old_action_receipts(monkeypatch):
    import jira_agent.approvals as approvals
    monkeypatch.setattr(approvals, '_MAX_APPROVALS', 1)
    ledger = ActionLedger()
    rc = context(ledger)
    t = load_tools()['jira_create_issue']
    code = execute(t, rc, ARGS)['code']
    rc.last_user_text = f'ja {code}'
    execute(t, rc, {**ARGS, 'confirmation_code': code})
    rc.last_user_text = 'neues Ticket'
    assert execute(t, rc, {**ARGS, 'summary': 'Anderes Ticket'})['error'] == 'ValueError'
    rc.last_user_text = f'ja {code}'
    assert execute(t, rc, {**ARGS, 'confirmation_code': code})['already_executed']


def test_runtime_preserves_approval_across_requests_and_scopes_it_to_chat(monkeypatch):
    import jira_agent.runtime as runtime
    from jira_agent.state import UserState
    jira = FakeJira()
    state = UserState(creds={'jira_token':'fake'}, jira_user='jira-user',
                      settings=dict(runtime.DEFAULT_SETTINGS), skills={})
    monkeypatch.setattr(runtime,'user_state',lambda email:state)
    monkeypatch.setattr(runtime,'JiraClient',lambda *a:jira)
    monkeypatch.setattr(runtime,'build_model',lambda *a:'test-model')
    monkeypatch.setitem(runtime.CFG['agent'],'enabled_tools',['jira_create_issue'])
    headers = {'x-forwarded-email':'test@example.test'}
    tool = load_tools()['jira_create_issue']
    _, first = runtime.prepare(headers, [{'role':'user','content':'Erstelle ein Ticket'}], 'chat-1')
    code = execute(tool, first, ARGS)['code']
    message = [{'role':'user','content':f'ja {code}'}]
    _, wrong = runtime.prepare(headers, message, 'chat-2')
    assert execute(tool,wrong,{**ARGS,'confirmation_code':code})['status'] == 'BESTAETIGUNG_NOETIG'
    for number in range(2):
        _, again = runtime.prepare(headers, message, 'chat-1')
        result = execute(tool,again,{**ARGS,'confirmation_code':code})
        assert result['key'] == 'ABC-1'
        assert result.get('already_executed',False) == (number > 0)
    assert len(jira.issues) == 1
