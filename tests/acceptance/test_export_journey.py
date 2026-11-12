"""Acceptance: a user's export contains every ticket, or explicitly explains why it does not."""
import csv
import io

import pytest

from jira_agent.testing import FakeJira, FakeFiles, FakeResponse, run_tool
from jira_agent.tools.jira_tools import export_issues


def jira_with_tickets(count=150):
    return FakeJira(issues={f'ABC-{n}':{'summary':f'Ticket {n}'} for n in range(1,count+1)})


def test_export_150_tickets_is_complete_not_first_100():
    jira,files=jira_with_tickets(),FakeFiles()
    result=run_tool('export_file',jira=jira,files=files,source='jql',query='project = ABC',format='csv')
    rows=list(csv.reader(io.StringIO(next(iter(files.files.values()))[1].decode('utf-8-sig')),delimiter=';'))
    assert result['zeilen']==150 and result['total']==150 and not result['truncated']
    assert len(rows)==151 and len({r[0] for r in rows[1:]})==150
    assert [c[2]['startAt'] for c in jira.calls if c[1]=='/search']==[0,100]
    assert result['next_start_at'] is None


def test_server_page_cap_does_not_skip_tickets(monkeypatch):
    jira=jira_with_tickets(7)
    original=jira.request
    def capped(method,path,**kwargs):
        if path=='/search':kwargs['params']={**kwargs['params'],'maxResults':2}
        return original(method,path,**kwargs)
    monkeypatch.setattr(jira,'request',capped)
    result=export_issues(jira,'project = ABC',100)
    assert len(result['issues'])==7 and not result['truncated']
    assert [c[2]['startAt'] for c in jira.calls]==[0,2,4,6]


def test_capped_export_can_continue_with_explicit_next_position(monkeypatch):
    import jira_agent.tools.output_tools as output
    monkeypatch.setattr(output,'_EXPORT_ROWS',3)
    jira=jira_with_tickets(7)
    all_keys=[]
    offset=0
    for index in range(3):
        files=FakeFiles()
        result=run_tool('export_file',jira=jira,files=files,source='jql',query='project = ABC',format='csv',start_at=offset)
        rows=list(csv.reader(io.StringIO(next(iter(files.files.values()))[1].decode('utf-8-sig')),delimiter=';'))
        all_keys.extend(r[0] for r in rows[1:])
        if index<2:
            assert result['truncated'] and result['warning']
            offset=result['next_start_at']
        else:assert not result['truncated']
    assert len(all_keys)==len(set(all_keys))==7


@pytest.mark.parametrize('mode',['duplicates','changed_total','empty_page','missing_total','wrong_start'])
def test_inconsistent_pages_never_claim_completeness(monkeypatch,mode):
    jira=jira_with_tickets(150)
    original=jira.request
    def inconsistent(method,path,**kwargs):
        response=original(method,path,**kwargs)
        if path!='/search':return response
        data=response.json()
        if mode=='missing_total':data.pop('total')
        elif kwargs['params']['startAt']:
            if mode=='duplicates':data['issues']=[jira._jira_issue('ABC-1')]
            if mode=='changed_total':data['total']+=1
            if mode=='empty_page':data['issues']=[]
            if mode=='wrong_start':data['startAt']=0
        return FakeResponse(200,data)
    monkeypatch.setattr(jira,'request',inconsistent)
    result=export_issues(jira,'project = ABC',5000)
    assert result['truncated'] and result['warning']


def test_export_timeout_is_reported_as_partial(monkeypatch):
    import jira_agent.tools.jira_tools as tools
    ticks=iter([0,0,61])
    monkeypatch.setattr(tools.time,'monotonic',lambda:next(ticks))
    result=export_issues(jira_with_tickets(),'project = ABC',5000)
    assert len(result['issues'])==100 and result['truncated']
    assert 'Zeitlimit' in result['warning']


def test_chat_search_exposes_continuation_position():
    result=run_tool('jira_search',jira=jira_with_tickets(70),jql='project = ABC',max_results=50)
    assert result['truncated'] and result['next_start_at']==50
