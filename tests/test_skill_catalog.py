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
        self.append_only = False

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

        def newest(name):
            same = [r for r in self.rows if r['name'] == name]
            return max(same, key=lambda r: r['version']) if same else None

        if statement.startswith('DELETE'):
            if self.append_only:
                return self._response(error="[DELTA_CANNOT_MODIFY_APPEND_ONLY] This table is configured to only allow "
                                            "appends. If you would like to permit updates or deletes, use 'ALTER TABLE "
                                            "<table_name> SET TBLPROPERTIES (delta.appendOnly=false)'.")
            gone = [r for r in self.rows if r['name'] == p['name'] and r['owner'] == p['owner']]
            self.rows = [r for r in self.rows if r not in gone]
            return self._response([[str(len(gone))]])
        if statement.startswith('INSERT'):
            last = newest(p['name'])
            if "'withdrawn'" in statement:
                if not last or last['owner'] != p['owner'] or last['status'] != 'published':
                    return self._response([['0']])
                self.rows.append({**last, 'version': last['version'] + 1, 'status': 'withdrawn'})
                return self._response([['1']])
            if last and last['owner'] != p['owner']:
                return self._response([['0']])
            self.rows.append({'name': p['name'], 'version': (last['version'] if last else 0) + 1, 'status': 'published',
                              'description': p['description'], 'instructions': p['instructions'], 'owner': p['owner']})
            return self._response([['1']])
        if 'ROW_NUMBER' in statement:
            latest = {r['name']: newest(r['name']) for r in self.rows}
            return self._response([[r['name'], str(r['version']), r['description'], r['owner'], '2026-11-17 10:00:00']
                                   for r in sorted(latest.values(), key=lambda r: r['name']) if r['status'] == 'published'])
        if statement.startswith('SELECT version, status, owner'):
            last = newest(p['name'])
            return self._response([[str(last['version']), last['status'], last['owner']]] if last else [])
        matches = [r for r in self.rows if r['name'] == p['name'] and r['status'] == 'published' and
                   r['version'] == int(p['version'])]
        if not matches:
            return self._response([])
        r = matches[0]
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


def test_setup_sql_quotes_identifiers_and_allows_removal():
    ddl = registry.setup_sql('my_catalog', 'my_schema')[0]
    assert '`my_catalog`.`my_schema`.`skill_versions`' in ddl
    assert 'appendOnly' not in ddl
    assert registry.allow_removal_sql('my_catalog', 'my_schema') == (
        'ALTER TABLE `my_catalog`.`my_schema`.`skill_versions` SET TBLPROPERTIES (delta.appendOnly = false)')
    for bad in ('a.b', 'a`b', "x'; DROP TABLE t; --", ''):
        with pytest.raises(ValueError):
            registry.setup_sql(bad, 'ok')
        with pytest.raises(ValueError):
            registry.allow_removal_sql(bad, 'ok')


def test_documented_setup_sql_matches_the_code():
    from pathlib import Path
    doc = (Path(__file__).resolve().parent.parent / 'docs' / 'REGISTRY.md').read_text(encoding='utf-8')
    block = doc.split('```sql\n', 1)[1].split('\n```', 1)[0]
    assert block == registry.setup_sql(CFG['registry']['catalog'], CFG['registry']['schema'])[0]
    assert registry.allow_removal_sql(CFG['registry']['catalog'], CFG['registry']['schema']) in doc


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


@pytest.mark.parametrize('error, expected', [
    ("[INSUFFICIENT_PERMISSIONS] Insufficient privileges:\nPrincipal 'Doe, Jane' does not have USE CATALOG on "
     "Catalog 'ude_dev_we_cariad_t1s_sandbox'. SQLSTATE: 42501",
     'You are missing USE CATALOG on catalog ude_dev_we_cariad_t1s_sandbox. Ask the owner of the catalog'),
    ("[INSUFFICIENT_PERMISSIONS] Insufficient privileges:\nUser does not have USE SCHEMA on Schema "
     "'cat.t1_jira_agent'.", 'You are missing USE SCHEMA on schema cat.t1_jira_agent. Ask the owner of the schema'),
    ("[INSUFFICIENT_PERMISSIONS] User does not have MODIFY on Table 'cat.s.skill_versions'. User does not have "
     "MODIFY on Table 'cat.s.skill_versions'.",
     'You are missing MODIFY on table cat.s.skill_versions. Ask the owner of the skill catalog table'),
    ('ModifyTable is not supported in read-only session mode.', 'only allows reading'),
])
def test_permission_failures_name_exactly_what_is_missing(warehouse, error, expected):
    reg = registry.SkillRegistry(SimpleNamespace(statement_execution=warehouse), 'wh')
    warehouse.error = error
    with pytest.raises(registry.RegistryError) as exc:
        reg.publish({'name': 'sprint-notes', **SKILL}, ALICE)
    assert expected in str(exc.value)
    assert 'Doe' not in str(exc.value) and 'SQLSTATE' not in str(exc.value)


def test_unknown_privileges_and_odd_names_are_not_echoed():
    assert registry.missing_privileges("does not have DROP EVERYTHING on Table 'a.b.c'") == []
    assert registry.missing_privileges("does not have SELECT on Table 'a.b; <script>'") == []
    assert registry.missing_privileges("does not have SELECT on Table 'a.b.c'") == [('SELECT', 'table', 'a.b.c')]


def test_rejected_requests_explain_warehouse_and_sign_in_problems(warehouse):
    from databricks.sdk.errors import PermissionDenied, Unauthenticated

    class Rejecting:
        def __init__(self, exc):
            self.exc = exc

        def execute_statement(self, **kwargs):
            raise self.exc

    def reg(exc):
        return registry.SkillRegistry(SimpleNamespace(statement_execution=Rejecting(exc)), 'wh-123')

    with pytest.raises(registry.RegistryError, match='CAN USE on the SQL warehouse wh-123'):
        reg(PermissionDenied('You are not authorized to use this warehouse')).list_latest()
    with pytest.raises(registry.RegistryError, match='sign-in to this app is missing permissions'):
        reg(PermissionDenied('Provided OAuth token does not have required scopes: sql')).list_latest()
    with pytest.raises(registry.RegistryError, match='sign-in'):
        reg(Unauthenticated('Invalid token')).list_latest()
    with pytest.raises(ValueError):
        reg(ValueError('other errors are not hidden')).list_latest()


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


def test_list_shows_who_published_what_to_publisher_and_colleagues(make_client, warehouse):
    alice, bob = make_client(ALICE), make_client(BOB)
    alice.put('/jira/api/skills/sprint-notes', json=SKILL)
    before = {s['name']: s for s in alice.get('/jira/api/skills').json()}
    assert before['sprint-notes']['quelle'] == 'persoenlich' and 'published' not in before['sprint-notes']
    alice.post('/jira/api/registry/skills/sprint-notes/publish')
    mine = {s['name']: s for s in alice.get('/jira/api/skills').json()}['sprint-notes']
    assert mine['quelle'] == 'persoenlich'
    assert mine['published'] == {'version': 1, 'owner': ALICE, 'owner_name': 'alice', 'mine': True}
    seen = {s['name']: s for s in bob.get('/jira/api/skills').json()}['sprint-notes']
    assert (seen['quelle'], seen['version'], seen['owner_name'], seen['mine']) == ('katalog', 1, 'alice', False)
    assert 'published' not in seen
    alice.put('/jira/api/skills/sprint-notes', json={**SKILL, 'anleitung': 'changed'})
    alice.post('/jira/api/registry/skills/sprint-notes/publish')
    assert {s['name']: s for s in alice.get('/jira/api/skills').json()}['sprint-notes']['published']['version'] == 2
    # Colleagues' skill lists are cached for a few minutes; they see the new version after that (or a reload of the cache).
    assert {s['name']: s for s in bob.get('/jira/api/skills').json()}['sprint-notes']['version'] == 1
    user_state(BOB).catalog_skills = None
    assert {s['name']: s for s in bob.get('/jira/api/skills').json()}['sprint-notes']['version'] == 2


def test_personal_skill_with_a_name_owned_by_someone_else_is_flagged(make_client, warehouse):
    alice, bob = make_client(ALICE), make_client(BOB)
    alice.put('/jira/api/skills/sprint-notes', json=SKILL)
    alice.post('/jira/api/registry/skills/sprint-notes/publish')
    bob.put('/jira/api/skills/sprint-notes', json={**SKILL, 'anleitung': 'bobs own'})
    own = {s['name']: s for s in bob.get('/jira/api/skills').json()}['sprint-notes']
    assert own['quelle'] == 'persoenlich'
    assert own['published']['mine'] is False and own['published']['owner_name'] == 'alice'


def test_remove_deletes_every_row_and_frees_the_name(warehouse):
    reg = registry.SkillRegistry(SimpleNamespace(statement_execution=warehouse), 'wh')
    skill = {'name': 'sprint-notes', **SKILL}
    reg.publish(skill, ALICE)
    reg.publish({**skill, 'anleitung': 'second'}, ALICE)
    with pytest.raises(registry.RegistryError, match='Only alice@example.test can remove'):
        reg.remove('sprint-notes', BOB)
    with pytest.raises(registry.RegistryError, match='not in the catalog'):
        reg.remove('never-published', ALICE)
    assert len(warehouse.rows) == 2
    assert reg.remove('sprint-notes', ALICE) == {'name': 'sprint-notes', 'removed': True, 'hidden': False}
    assert warehouse.rows == [] and reg.list_latest() == [] and reg.get('sprint-notes') is None
    assert reg.publish(skill, BOB)['version'] == 1     # the name is free again for anyone
    delete = next(s for s, _ in warehouse.statements if s.startswith('DELETE'))
    assert 'owner = :owner' in delete and 'skill_name = :name' in delete


def test_remove_only_hides_when_the_table_was_created_append_only(warehouse):
    warehouse.append_only = True
    reg = registry.SkillRegistry(SimpleNamespace(statement_execution=warehouse), 'wh')
    skill = {'name': 'sprint-notes', **SKILL}
    reg.publish(skill, ALICE)
    reg.publish({**skill, 'anleitung': 'second'}, ALICE)
    result = reg.remove('sprint-notes', ALICE)
    assert (result['removed'], result['hidden']) == (False, True)
    assert [r['status'] for r in warehouse.rows] == ['published', 'published', 'withdrawn']   # nothing deleted
    assert reg.list_latest() == [] and reg.get('sprint-notes') is None and reg.get('sprint-notes', 1) is None
    assert reg.remove('sprint-notes', ALICE)['hidden'] is True and len(warehouse.rows) == 3
    with pytest.raises(registry.RegistryError, match='already published by alice'):
        reg.publish({**skill, 'anleitung': 'takeover'}, BOB)     # a hidden name stays reserved for its owner
    again = reg.publish(skill, ALICE)
    assert again['version'] == 4 and [s['name'] for s in reg.list_latest()] == ['sprint-notes']


def test_remove_through_the_app_for_owner_and_colleague(make_client, warehouse):
    alice, bob = make_client(ALICE), make_client(BOB)
    alice.put('/jira/api/skills/sprint-notes', json=SKILL)
    alice.post('/jira/api/registry/skills/sprint-notes/publish')
    seen = {s['name']: s for s in bob.get('/jira/api/skills').json()}['sprint-notes']
    assert seen['mine'] is False
    denied = bob.post('/jira/api/registry/skills/sprint-notes/remove')
    assert denied.status_code == 409 and 'Only alice' in denied.json()['detail']
    assert bob.post('/jira/api/registry/skills/BAD NAME/remove').status_code == 400
    done = alice.post('/jira/api/registry/skills/sprint-notes/remove')
    assert done.status_code == 200 and done.json() == {'name': 'sprint-notes', 'removed': True, 'hidden': False}
    assert warehouse.rows == []
    mine = {s['name']: s for s in alice.get('/jira/api/skills').json()}['sprint-notes']
    assert mine['quelle'] == 'persoenlich' and 'published' not in mine     # personal copy remains, no catalog badge
    user_state(BOB).catalog_skills = None
    assert 'sprint-notes' not in {s['name'] for s in bob.get('/jira/api/skills').json()}
    assert bob.get('/jira/api/skills/sprint-notes').status_code == 404
    assert alice.post('/jira/api/registry/skills/sprint-notes/remove').status_code == 409     # nothing left to remove
    assert alice.post('/jira/api/registry/skills/sprint-notes/publish').json()['version'] == 1


def test_remove_reports_when_it_could_only_hide_the_skill(make_client, warehouse):
    warehouse.append_only = True
    alice = make_client(ALICE)
    alice.put('/jira/api/skills/sprint-notes', json=SKILL)
    alice.post('/jira/api/registry/skills/sprint-notes/publish')
    result = alice.post('/jira/api/registry/skills/sprint-notes/remove').json()
    assert result == {'name': 'sprint-notes', 'removed': False, 'hidden': True}
    assert [r['status'] for r in warehouse.rows] == ['published', 'withdrawn']


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
    # The same lazy loading works when the skill is named inside a sentence, through the real request path.
    text = 'Please use /sprint-notes and /other-skill today.'
    for name, _, _ in runtime.find_invocations(text, skills):
        skills = runtime.with_skill_instructions(state, 't', skills, name)
    mid = runtime.skills_prompt(skills, text)
    assert 'Search my tickets' in mid and 'Other steps' in mid and 'inside their message' in mid


def test_own_and_team_skills_win_over_catalog_and_missing_instructions_are_not_invented(warehouse):
    reg = registry.SkillRegistry(SimpleNamespace(statement_execution=warehouse), 'wh')
    reg.publish({'name': 'triage', 'beschreibung': 'Catalog copy', 'anleitung': 'catalog steps'}, ALICE)
    state = user_state(BOB)
    merged = runtime.with_catalog_skills(state, 't', {'triage': {'name': 'triage', 'beschreibung': 'Team',
                                                                'anleitung': 'team steps', 'quelle': 'team'}})
    assert merged['triage']['quelle'] == 'team'
    warehouse.rows.append({'name': 'late-skill', 'version': 1, 'status': 'published', 'description': 'x',
                           'instructions': 'y', 'owner': ALICE})
    state.catalog_skills = None
    merged = runtime.with_catalog_skills(state, 't', {})
    warehouse.error = '[INSUFFICIENT_PERMISSIONS] now denied'
    failed = runtime.with_skill_instructions(state, 't', merged, 'late-skill')
    assert 'could not be loaded' in failed['late-skill']['anleitung']
