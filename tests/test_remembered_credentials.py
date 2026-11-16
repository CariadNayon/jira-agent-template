"""Encrypted workspace storage, OBO isolation and reconnect/forget behavior."""
import concurrent.futures
import io
import json
import os
import threading

from cryptography.fernet import Fernet
from databricks.sdk.errors import NotFound
from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from jira_agent import CFG
from jira_agent.credentials import JiraTokenStore, SavedTokenError
from jira_agent.jira_client import JiraClient, JiraError
from jira_agent.state import logout, user_state

OWNER = 'remembered@example.test'
OTHER = 'other@example.test'
PAT = 'private-jira-fixture-token'


class Workspace:
    def __init__(self, owner, disk):
        self.owner, self.disk = owner, disk
        self.calls = []
        self.fail_write = self.fail_delete = False

    def check(self, path):
        assert path.startswith(f'/Users/{self.owner}/.jira-agent/credentials/')

    def mkdirs(self, path):
        self.check(path + '/')

    def upload(self, path, stream, **kwargs):
        self.check(path)
        if self.fail_write:
            raise RuntimeError('PRIVATE-SERVICE-ERROR')
        self.disk[path] = stream.read()
        self.calls.append(('save', path))

    def download(self, path):
        self.check(path)
        self.calls.append(('load', path))
        if path not in self.disk:
            raise NotFound()
        return io.BytesIO(self.disk[path])

    def delete(self, path):
        self.check(path)
        if self.fail_delete:
            raise RuntimeError('PRIVATE-SERVICE-ERROR')
        self.calls.append(('delete', path))
        if path not in self.disk:
            raise NotFound()
        del self.disk[path]


@pytest.fixture
def storage(monkeypatch):
    from types import SimpleNamespace
    import jira_agent.web as web
    import jira_agent.runtime as runtime
    monkeypatch.setenv('JIRA_TOKEN_ENCRYPTION_KEY', Fernet.generate_key().decode())
    disk = {}
    clients = {owner: SimpleNamespace(workspace=Workspace(owner, disk)) for owner in (OWNER, OTHER)}
    def user_client(obo):
        assert obo.startswith('obo:')
        return clients[obo[4:]]
    monkeypatch.setattr(web, 'user_client', user_client)
    monkeypatch.setattr(runtime, 'user_client', user_client)
    calls = []
    rejection = [None]
    def myself(jira):
        calls.append(jira._headers['Authorization'])
        if rejection[0]:
            raise rejection[0]
        return {'name':'jira.user','displayName':'Jira User'}
    monkeypatch.setattr(JiraClient, 'myself', myself)
    for owner in clients:
        logout(owner)
        user_state(owner).settings = dict(runtime.DEFAULT_SETTINGS)
        user_state(owner).skills = {}
    app = FastAPI()
    web.install(app)
    client = TestClient(app, headers={'x-forwarded-email':OWNER,'x-forwarded-access-token':'obo:'+OWNER})
    yield client, clients, disk, calls, rejection
    for owner in clients:
        logout(owner)


def connect(client, remember=True, token=PAT):
    return client.post('/jira/api/credentials', json={'jira_token':token,'remember_jira':remember})


def test_remember_encrypts_and_restores_after_memory_session_is_lost(storage):
    client, clients, disk, calls, _ = storage
    response = connect(client)
    assert response.status_code == 200 and response.json()['jira_remembered']
    assert PAT not in response.text
    assert len(disk) == 1
    blob = next(iter(disk.values()))
    assert PAT.encode() not in blob and b'owner' not in blob
    assert user_state(OWNER).creds['jira_token'] == PAT
    logout(OWNER)  # Simulate a restart/session expiry, not the explicit Forget endpoint.
    status = client.get('/jira/api/me').json()
    assert status['has_jira_token'] and status['has_saved_jira_token']
    assert status['remember_jira_available']
    assert status['remember_jira_reason'] == status['remember_jira_message'] == ''
    assert status['jira_user'] == 'jira.user | Jira User'
    assert PAT not in json.dumps(status)
    assert calls == ['Bearer '+PAT, 'Bearer '+PAT]
    before = len(clients[OWNER].workspace.calls)
    client.get('/jira/api/me')
    assert len(clients[OWNER].workspace.calls) == before


def test_other_user_cannot_restore_owner_token_even_if_ciphertext_is_copied(storage):
    client, clients, disk, calls, _ = storage
    connect(client)
    status = client.get('/jira/api/me', headers={'x-forwarded-email':OTHER,'x-forwarded-access-token':'obo:'+OTHER}).json()
    assert not status['has_jira_token']
    other_store = JiraTokenStore(clients[OTHER], OTHER)
    disk[other_store.path] = next(iter(disk.values()))
    with pytest.raises(SavedTokenError, match='cannot be read'):
        other_store.load()
    assert calls == ['Bearer '+PAT]


def test_ciphertext_is_bound_to_app_and_jira_url(storage, monkeypatch):
    client, clients, disk, _, _ = storage
    connect(client)
    original_path, original = next(iter(disk.items()))
    monkeypatch.setenv('DATABRICKS_APP_NAME', 'another-app')
    store = JiraTokenStore(clients[OWNER], OWNER)
    assert store.path != original_path
    disk[store.path] = original
    with pytest.raises(SavedTokenError):
        store.load()
    monkeypatch.setitem(CFG['jira'], 'base_url', 'https://other.example.test/rest/api/2')
    store = JiraTokenStore(clients[OWNER], OWNER)
    disk[store.path] = original
    with pytest.raises(SavedTokenError):
        store.load()


def test_rejected_saved_token_never_becomes_an_active_credential(storage):
    client, _, _, calls, rejection = storage
    connect(client)
    logout(OWNER)
    rejection[0] = JiraError('Denied', status_code=401)
    status = client.get('/jira/api/me').json()
    assert not status['has_jira_token'] and status['has_saved_jira_token']
    assert 'rejected' in status['jira_connection_message']
    assert not user_state(OWNER).creds
    client.get('/jira/api/me')
    assert len(calls) == 2


def test_transient_restore_failure_has_backoff_and_can_retry(storage, monkeypatch):
    client, _, _, calls, rejection = storage
    connect(client)
    logout(OWNER)
    rejection[0] = JiraError('Network unavailable')
    assert not client.get('/jira/api/me').json()['has_jira_token']
    client.get('/jira/api/me')
    assert len(calls) == 2
    user_state(OWNER).jira_restore_retry_at = 0
    rejection[0] = None
    assert client.get('/jira/api/me').json()['has_jira_token']


def test_expired_tampered_and_wrong_key_records_do_not_restore(storage, monkeypatch):
    client, clients, disk, calls, _ = storage
    connect(client)
    path, blob = next(iter(disk.items()))
    seal = Fernet(os.environ['JIRA_TOKEN_ENCRYPTION_KEY'].encode())
    payload = json.loads(seal.decrypt(blob))
    payload['expires_at'] = 1
    disk[path] = seal.encrypt(json.dumps(payload).encode())
    with pytest.raises(SavedTokenError, match='expired'):
        JiraTokenStore(clients[OWNER], OWNER).load()
    disk[path] = blob[:-5] + b'xxxxx'
    with pytest.raises(SavedTokenError):
        JiraTokenStore(clients[OWNER], OWNER).load()
    disk[path] = blob
    monkeypatch.setenv('JIRA_TOKEN_ENCRYPTION_KEY', Fernet.generate_key().decode())
    logout(OWNER)
    status = client.get('/jira/api/me').json()
    assert not status['has_jira_token'] and 'cannot be read' in status['jira_connection_message']
    assert calls == ['Bearer '+PAT]


def test_forget_deletes_saved_copy_and_does_not_reconnect(storage):
    client, _, disk, _, _ = storage
    connect(client)
    user_state(OWNER).creds['azure_key'] = 'private-azure-fixture'
    response = client.delete('/jira/api/credentials')
    assert response.status_code == 200 and response.json()['saved_token_deleted']
    assert not disk
    status = client.get('/jira/api/me').json()
    assert not status['has_jira_token'] and not status['has_azure_key'] and not status['has_saved_jira_token']


def test_session_only_replacement_removes_previous_saved_copy(storage):
    client, _, disk, _, _ = storage
    connect(client)
    response = connect(client, remember=False, token='temporary-fixture')
    assert response.status_code == 200 and not response.json()['jira_remembered']
    assert not disk
    logout(OWNER)
    assert not client.get('/jira/api/me').json()['has_jira_token']


def test_failed_save_and_failed_forget_do_not_claim_success_or_leak_details(storage):
    client, clients, disk, _, _ = storage
    clients[OWNER].workspace.fail_write = True
    response = connect(client)
    assert response.status_code == 502
    assert not user_state(OWNER).creds and not disk
    assert PAT not in response.text and 'PRIVATE-SERVICE-ERROR' not in response.text
    clients[OWNER].workspace.fail_write = False
    connect(client)
    clients[OWNER].workspace.fail_delete = True
    response = client.delete('/jira/api/credentials')
    assert response.status_code == 502 and 'could not be deleted' in response.text
    assert disk and user_state(OWNER).creds['jira_token'] == PAT


@pytest.mark.parametrize('key', ['', 'invalid-fernet-key'])
def test_missing_key_disables_remember_but_keeps_session_connection(storage, monkeypatch, key):
    client, _, disk, _, _ = storage
    monkeypatch.setenv('JIRA_TOKEN_ENCRYPTION_KEY', key)
    status = client.get('/jira/api/me').json()
    assert not status['remember_jira_available']
    assert status['remember_jira_reason'] == ('invalid_encryption_key' if key else 'missing_encryption_key')
    assert 'encryption secret' in status['remember_jira_message']
    assert not key or key not in json.dumps(status)
    assert connect(client).status_code == 400
    assert connect(client, remember=False).status_code == 200
    assert not disk


def test_no_databricks_user_authorization_cannot_save(storage):
    client, _, disk, _, _ = storage
    status = client.get('/jira/api/me', headers={'x-forwarded-access-token':''}).json()
    assert not status['remember_jira_available']
    assert status['remember_jira_reason'] == 'missing_user_authorization'
    assert 'Sign in again' in status['remember_jira_message']
    response = client.post('/jira/api/credentials', headers={'x-forwarded-access-token':''},
                           json={'jira_token':PAT,'remember_jira':True})
    assert response.status_code == 400 and not disk


def test_concurrent_restore_validates_jira_once(storage):
    import jira_agent.credentials as credentials
    client, _, _, calls, _ = storage
    connect(client)
    logout(OWNER)
    state = user_state(OWNER)
    barrier = threading.Barrier(4)
    def restore():
        barrier.wait(timeout=5)
        credentials.restore_jira(state, OWNER, 'obo:'+OWNER)
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
        list(executor.map(lambda _: restore(), range(4)))
    assert calls == ['Bearer '+PAT, 'Bearer '+PAT]


def test_direct_agent_request_restores_without_sending_credentials_to_model(storage, monkeypatch):
    import jira_agent.runtime as runtime
    client, _, _, _, _ = storage
    connect(client)
    logout(OWNER)
    monkeypatch.setattr(runtime, 'build_model', lambda *args: 'fixture-model')
    agent, context = runtime.prepare({'x-forwarded-email':OWNER,'x-forwarded-access-token':'obo:'+OWNER},
                                      [{'role':'user','content':'Show my tickets'}], 'chat')
    assert context.tool_ctx.jira._headers['Authorization'] == 'Bearer '+PAT
    assert PAT not in agent.instructions


def test_memory_expiry_reconnects_and_metadata_is_not_cached(storage):
    client, _, _, calls, _ = storage
    connect(client)
    user_state(OWNER).created = 0
    response = client.get('/jira/api/me')
    assert response.json()['has_jira_token']
    assert response.headers['Cache-Control'] == 'private, no-store'
    assert calls == ['Bearer '+PAT, 'Bearer '+PAT]


def test_forget_works_even_if_encryption_key_is_lost(storage, monkeypatch):
    client, _, disk, _, _ = storage
    connect(client)
    monkeypatch.delenv('JIRA_TOKEN_ENCRYPTION_KEY')
    assert client.delete('/jira/api/credentials').status_code == 200
    assert not disk


def test_forget_without_remember_is_not_blocked_by_workspace_errors(storage, monkeypatch):
    client, clients, _, _, _ = storage
    assert connect(client, remember=False).status_code == 200
    monkeypatch.delenv('JIRA_TOKEN_ENCRYPTION_KEY')
    clients[OWNER].workspace.fail_delete = True
    response = client.delete('/jira/api/credentials')
    assert response.status_code == 200 and not response.json()['saved_token_deleted']
    assert not user_state(OWNER).creds


def test_forget_still_reports_failure_when_a_saved_copy_exists(storage):
    client, clients, disk, _, _ = storage
    connect(client)
    clients[OWNER].workspace.fail_delete = True
    assert client.delete('/jira/api/credentials').status_code == 502
    assert disk


def test_workspace_client_cannot_write_to_another_users_home(storage):
    client, _, disk, _, _ = storage
    response = client.post('/jira/api/credentials', headers={'x-forwarded-email':OTHER},
                           json={'jira_token':PAT,'remember_jira':True})
    assert response.status_code == 502 and not disk
    assert not user_state(OTHER).creds
