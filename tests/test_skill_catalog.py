"""Shared skill catalog: append-only versions, ownership, lazy loading and the user-facing endpoints."""
from types import SimpleNamespace

import pytest
from databricks.sdk.service.sql import StatementState
from fastapi import FastAPI
from fastapi.testclient import TestClient

import jira_agent.registry as registry
import jira_agent.runtime as runtime
import jira_agent.web as web
from jira_agent import CFG
from jira_agent.state import logout, user_state

ALICE, BOB = 'alice@example.test', 'bob@example.test'
SKILL = {'beschreibung': 'Weekly report', 'anleitung': '1. Search my tickets.\n2. Summarize.'}


class FakeWarehouse:
    """Mimics the few statements of the catalog, including the ownership check of the INSERT."""

    def __init__(self):
        self.rows, self.statements, self.error = [], [], None

    @staticmethod
    def _response(rows=None, error=None):
        code = SimpleNamespace(value='PARSE_SYNTAX_ERROR')
        status = SimpleNamespace(state=StatementState.FAILED if error else StatementState.SUCCEEDED,
                                 error=SimpleNamespace(message=error, error_code=code) if error else None)
        return SimpleNamespace(statement_id='s1', status=status, result=SimpleNamespace(data_array=rows or []))

    def execute_statement(self, statement, warehouse_id, parameters=None, wait_timeout=None, row_limit=None):
        p = {item.name: item.value for item in parameters or []}
        self.statements.append((statement, p))
        if self.error:
            return self._response(error=self.error)
        if statement.startswith('INSERT'):
            same = [r for r in self.rows if r['name'] == p['name']]
            if same and max(same, key=lambda r: r['version'])['owner'] != p['owner']:
                return self._response([['0']])
            self.rows.append({'name': p['name'], 'version': max([r['version'] for r in same], default=0) + 1,
                              'description': p['description'], 'instructions': p['instructions'], 'owner': p['owner']})
            return self._response([['1']])
        if 'QUALIFY' in statement:
            latest = {}
            for r in self.rows:
                if r['name'] not in latest or r['version'] > latest[r['name']]['version']:
                    latest[r['name']] = r
            return self._response([[r['name'], str(r['version']), r['description'], r['owner'], '2026-11-17 10:00:00']
                                   for r in sorted(latest.values(), key=lambda r: r['name'])])
        matches = [r for r in self.rows if r['name'] == p['name'] and
                   ('version' not in p or r['version'] == int(p['version']))]
        if not matches:
            return self._response([])
        r = max(matches, key=lambda r: r['version'])
        return self._response([[r['name'], str(r['version']), r['description'], r['owner'], '2026-11-17 10:00:00',
                                r['instructions']]])


@pytest.fixture
def warehouse(monkeypatch):
    fake = FakeWarehouse()
    client = SimpleNamespace(statement_execution=fake)
    monkeypatch.setitem(CFG['registry'], 'enabled', True)
    monkeypatch.setattr(web, 'user_client', lambda token: client)
    monkeypatch.setattr(runtime, 'user_client', lambda token: client)
    monkeypatch.setattr(web, 'WAREHOUSE_ID', 'wh')
    monkeypatch.setattr(runtime, 'WAREHOUSE_ID', 'wh')
    for user in (ALICE, BOB):
        logout(user)
    yield fake
    for user in (ALICE, BOB):
        logout(user)


@pytest.fixture
def make_client(monkeypatch, warehouse):
    personal = {ALICE: {}, BOB: {}}

    class Store:
        def __init__(self, w, email):
            self.email = email

        def load(self):
            return dict(personal[self.email])

        def save(self, skills):
            personal[self.email] = dict(skills)

    monkeypatch.setattr(web, 'PersonalSkillStore', Store)
    monkeypatch.setattr(runtime, 'PersonalSkillStore', Store)
    app = FastAPI()
    web.install(app)

    def make(email):
        return TestClient(app, headers={'x-forwarded-email': email, 'x-forwarded-access-token': 't'})
    return make


def test_setup_sql_is_append_only_and_quotes_identifiers():
    ddl = registry.setup_sql('my_catalog', 'my_schema')[0]
    assert '`my_catalog`.`my_schema`.`skill_versions`' in ddl
    assert 'delta.appendOnly = true' in ddl
    for bad in ('a.b', 'a`b', "x'; DROP TABLE t; --", ''):
        with pytest.raises(ValueError):
            registry.setup_sql(bad, 'ok')


def test_documented_setup_sql_matches_the_code():
    from pathlib import Path
    doc = (Path(__file__).resolve().parent.parent / 'docs' / 'REGISTRY.md').read_text(encoding='utf-8')
    block = doc.split('```sql\n', 1)[1].split('\n```', 1)[0]
    assert block == registry.setup_sql(CFG['registry']['catalog'], CFG['registry']['schema'])[0]


def test_catalog_is_disabled_by_default_and_ignores_invalid_configuration(monkeypatch):
    monkeypatch.setitem(CFG['registry'], 'enabled', False)
    assert not registry.enabled()
    monkeypatch.setitem(CFG['registry'], 'enabled', True)
    monkeypatch.setitem(CFG['registry'], 'schema', 'bad schema; DROP')
    assert not registry.enabled()


def test_publish_creates_numbered_versions_and_only_the_owner_adds_more(warehouse):
    reg = registry.SkillRegistry(SimpleNamespace(statement_execution=warehouse), 'wh')
    skill = {'name': 'sprint-notes', **SKILL}
    first = reg.publish(skill, ALICE)
    assert (first['version'], first['owner']) == (1, ALICE)
    assert reg.publish(skill, ALICE)['unchanged'] is True and len(warehouse.rows) == 1
    changed = reg.publish({**skill, 'anleitung': 'new text'}, ALICE)
    assert changed['version'] == 2 and reg.get('sprint-notes', 1)['anleitung'] == SKILL['anleitung']
    with pytest.raises(registry.RegistryError, match='already published by alice'):
        reg.publish({**skill, 'anleitung': 'takeover'}, BOB)
    assert len(warehouse.rows) == 2


def test_user_text_is_only_ever_sent_as_parameters(warehouse):
    reg = registry.SkillRegistry(SimpleNamespace(statement_execution=warehouse), 'wh')
    hostile = "x'); DROP TABLE t; --"
    reg.publish({'name': 'sprint-notes', 'beschreibung': hostile, 'anleitung': hostile}, ALICE)
    assert all(hostile not in statement for statement, _ in warehouse.statements)
    assert any(hostile in params.values() for _, params in warehouse.statements)


def test_failures_are_explained_without_leaking_details(warehouse):
    reg = registry.SkillRegistry(SimpleNamespace(statement_execution=warehouse), 'wh')
    warehouse.error = '[TABLE_OR_VIEW_NOT_FOUND] secret internal detail'
    with pytest.raises(registry.RegistryError, match='not set up') as missing:
        reg.list_latest()
    assert 'secret' not in str(missing.value)
    warehouse.error = '[INSUFFICIENT_PERMISSIONS] user has no privilege MODIFY'
    with pytest.raises(registry.RegistryError, match='do not have access'):
        reg.publish({'name': 'sprint-notes', **SKILL}, ALICE)
    warehouse.error = 'unexpected engine problem with internal detail'
    with pytest.raises(registry.RegistryError) as other:
        reg.list_latest()
    assert str(other.value) == 'The skill catalog request failed (PARSE_SYNTAX_ERROR).'
    assert 'internal detail' not in str(other.value)


def test_publish_and_use_through_the_app(make_client, warehouse):
    alice, bob = make_client(ALICE), make_client(BOB)
    assert alice.put('/jira/api/skills/sprint-notes', json=SKILL).status_code == 200
    published = alice.post('/jira/api/registry/skills/sprint-notes/publish')
    assert published.status_code == 200 and published.json()['version'] == 1
    listed = {s['name']: s for s in bob.get('/jira/api/skills').json()}
    assert listed['sprint-notes']['quelle'] == 'katalog' and listed['sprint-notes']['version'] == 1
    assert bob.get('/jira/api/skills/sprint-notes').json()['anleitung'] == SKILL['anleitung']
    # Bob cannot publish Alice's name, and only personal skills can be published at all.
    assert bob.put('/jira/api/skills/sprint-notes', json={**SKILL, 'anleitung': 'mine'}).status_code == 200
    assert bob.post('/jira/api/registry/skills/sprint-notes/publish').status_code == 409
    assert bob.post('/jira/api/registry/skills/triage/publish').status_code == 404
    status = bob.get('/jira/api/registry').json()
    assert status['enabled'] and status['location'].endswith('.' + CFG['registry']['schema'])


def test_endpoints_report_a_disabled_catalog(make_client, monkeypatch):
    monkeypatch.setitem(CFG['registry'], 'enabled', False)
    alice = make_client(ALICE)
    assert alice.get('/jira/api/registry').json() == {'enabled': False, 'location': '', 'message': ''}
    assert alice.post('/jira/api/registry/skills/sprint-notes/publish').status_code == 404
    assert 'katalog' not in {s['quelle'] for s in alice.get('/jira/api/skills').json()}


def test_catalog_problems_do_not_break_the_skill_list(make_client, warehouse):
    warehouse.error = '[INSUFFICIENT_PERMISSIONS] no SELECT'
    alice = make_client(ALICE)
    names = {s['name'] for s in alice.get('/jira/api/skills').json()}
    assert 'triage' in names
    assert 'do not have access' in alice.get('/jira/api/registry').json()['message']


def test_instructions_load_only_for_the_invoked_catalog_skill(warehouse):
    reg = registry.SkillRegistry(SimpleNamespace(statement_execution=warehouse), 'wh')
    reg.publish({'name': 'sprint-notes', **SKILL}, ALICE)
    reg.publish({'name': 'other-skill', 'beschreibung': 'Other', 'anleitung': 'Other steps'}, ALICE)
    state = user_state(BOB)
    skills = runtime.with_catalog_skills(state, 't', {})
    assert skills['sprint-notes']['anleitung'] == '' and skills['other-skill']['anleitung'] == ''
    loaded = runtime.with_skill_instructions(state, 't', skills, 'sprint-notes')
    assert loaded['sprint-notes']['anleitung'] == SKILL['anleitung'] and loaded['other-skill']['anleitung'] == ''
    prompt = runtime.skills_prompt(loaded, '/sprint-notes now')
    assert 'Search my tickets' in prompt and 'Other steps' not in prompt


def test_own_and_team_skills_win_over_catalog_and_missing_instructions_are_not_invented(warehouse):
    reg = registry.SkillRegistry(SimpleNamespace(statement_execution=warehouse), 'wh')
    reg.publish({'name': 'triage', 'beschreibung': 'Catalog copy', 'anleitung': 'catalog steps'}, ALICE)
    state = user_state(BOB)
    merged = runtime.with_catalog_skills(state, 't', {'triage': {'name': 'triage', 'beschreibung': 'Team',
                                                                'anleitung': 'team steps', 'quelle': 'team'}})
    assert merged['triage']['quelle'] == 'team'
    warehouse.rows.append({'name': 'late-skill', 'version': 1, 'description': 'x', 'instructions': 'y', 'owner': ALICE})
    state.catalog_skills = None
    merged = runtime.with_catalog_skills(state, 't', {})
    warehouse.error = '[INSUFFICIENT_PERMISSIONS] now denied'
    failed = runtime.with_skill_instructions(state, 't', merged, 'late-skill')
    assert 'could not be loaded' in failed['late-skill']['anleitung']
