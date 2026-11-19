"""Optional, encrypted Jira tokens in the signed-in user's workspace folder."""
from __future__ import annotations

import hashlib
import io
import json
import logging
import os
import re
import time

from jira_agent import BUNDLE, CFG
from jira_agent.jira_client import JiraClient, JiraError
from jira_agent.settings_store import settings_path

_KEY_ENV = 'JIRA_TOKEN_ENCRYPTION_KEY'
_MAX_BYTES = 16 * 1024


class SavedTokenError(ValueError):
    pass


_log = logging.getLogger('jira_agent.credentials')
_NO_WORKSPACE_RE = re.compile(r'unauthorized access to org', re.I)
_REMEMBER_OFF = 'or connect without "Remember for my account".'
STORAGE_MESSAGES = {
    'no_workspace_access': ('Your account has no access to the Databricks workspace behind this app, so the Jira '
                            'token cannot be remembered. Ask a workspace admin to add you to the workspace, '
                            + _REMEMBER_OFF),
    'missing_permission': ('Your sign-in does not allow the app to save files in your workspace folder. Sign out, '
                           'open the app in a new browser window and accept the requested permissions again.'),
    'missing_folder': ('Your Databricks home folder was not found. Open the Databricks workspace once so it is '
                       'created, then try again, ' + _REMEMBER_OFF),
}


def storage_problem(exc: Exception) -> str:
    """Classify a failure of the user's workspace storage without exposing service details."""
    from databricks.sdk.errors import NotFound, PermissionDenied, ResourceDoesNotExist, Unauthenticated
    if isinstance(exc, PermissionDenied) and _NO_WORKSPACE_RE.search(str(exc)):
        return 'no_workspace_access'
    if isinstance(exc, (PermissionDenied, Unauthenticated)):
        return 'missing_permission'
    if isinstance(exc, (NotFound, ResourceDoesNotExist)):
        return 'missing_folder'
    return 'unexpected'


def storage_message(problem: str, exc: Exception, unexpected: str) -> str:
    """User-facing text; unexpected errors only name the error type, never the service message."""
    return STORAGE_MESSAGES.get(problem) or f'{unexpected} ({type(exc).__name__}). Please try again.'


def log_storage_failure(action: str, email: str, exc: Exception, secret: str | None = None):
    """Log the cause for app owners; the Jira token is masked in case a service echoes it."""
    detail = ' '.join(str(exc).split())
    if secret:
        detail = detail.replace(secret, '***')
    _log.warning('Jira token %s failed for %s: %s: %s', action, email, type(exc).__name__, detail[:400])


def cipher():
    key = os.environ.get(_KEY_ENV, '').strip()
    if not key:
        return None
    try:
        # Already supplied by MLflow; no additional package or service is needed.
        from cryptography.fernet import Fernet
        return Fernet(key.encode('ascii'))
    except (ValueError, UnicodeError, ImportError):
        return None


def remember_availability(user_token: str | None) -> dict:
    """Explain prerequisites without revealing any secret or credential value."""
    if not os.environ.get(_KEY_ENV, '').strip():
        return {'available': False, 'reason': 'missing_encryption_key',
                'message': 'Remember is not set up yet. An app administrator must configure the encryption secret.'}
    if cipher() is None:
        return {'available': False, 'reason': 'invalid_encryption_key',
                'message': 'Remember is misconfigured. An app administrator must check the encryption secret.'}
    if not user_token:
        return {'available': False, 'reason': 'missing_user_authorization',
                'message': 'Sign in again and allow access to your personal workspace to use Remember.'}
    return {'available': True, 'reason': '', 'message': ''}


def remember_days() -> int:
    days = int(CFG['session'].get('remember_jira_days', 30))
    if not 1 <= days <= 365:
        raise ValueError('Remember duration must be between 1 and 365 days.')
    return days


class JiraTokenStore:
    def __init__(self, user_client, email: str):
        self.w = user_client
        app = os.environ.get('DATABRICKS_APP_NAME') or BUNDLE.get('app_name', 'jira-agent')
        self.binding = {'owner': email.casefold(), 'app': app, 'jira': CFG['jira']['base_url'].rstrip('/')}
        store_id = hashlib.sha256(json.dumps([app, self.binding['jira']]).encode()).hexdigest()[:32]
        self.path = settings_path(email).rsplit('/', 1)[0] + f'/credentials/{store_id}.enc'

    def save(self, token: str) -> int:
        from databricks.sdk.service.workspace import ImportFormat
        seal = cipher()
        if seal is None:
            raise SavedTokenError('Remembering Jira tokens is not configured for this app.')
        if not token or len(token) > 4096:
            raise SavedTokenError('Invalid Jira token length.')
        expires_at = int(time.time()) + remember_days()*24*3600
        payload = {'version': 1, **self.binding, 'expires_at': expires_at, 'token': token}
        encrypted = seal.encrypt(json.dumps(payload, separators=(',', ':')).encode())
        self.w.workspace.mkdirs(self.path.rsplit('/', 1)[0])
        self.w.workspace.upload(self.path, io.BytesIO(encrypted), format=ImportFormat.RAW, overwrite=True)
        return expires_at

    def load(self) -> dict | None:
        from databricks.sdk.errors import NotFound, ResourceDoesNotExist
        from cryptography.fernet import InvalidToken
        try:
            with self.w.workspace.download(self.path) as stream:
                encrypted = stream.read(_MAX_BYTES+1)
        except (NotFound, ResourceDoesNotExist):
            return None
        seal = cipher()
        if seal is None:
            raise SavedTokenError('Remembering Jira tokens is not configured for this app.')
        try:
            if len(encrypted) > _MAX_BYTES:
                raise ValueError()
            payload = json.loads(seal.decrypt(encrypted))
            if not isinstance(payload, dict) or payload.get('version') != 1:
                raise ValueError()
            if any(payload.get(k) != v for k, v in self.binding.items()):
                raise ValueError()
            token = payload.get('token')
            if not isinstance(token, str) or not token or len(token) > 4096:
                raise ValueError()
            expires = payload.get('expires_at')
            if not isinstance(expires, int):
                raise ValueError()
        except (InvalidToken, ValueError, TypeError, UnicodeError):
            raise SavedTokenError('The saved Jira token cannot be read. Connect again or forget the saved token.') from None
        if expires <= time.time():
            raise SavedTokenError('The saved Jira token has expired. Connect again or forget it.')
        return {'token': token, 'expires_at': expires}

    def delete(self):
        from databricks.sdk.errors import NotFound, ResourceDoesNotExist
        try:
            self.w.workspace.delete(self.path)
        except (NotFound, ResourceDoesNotExist):
            pass


def set_jira_identity(state, token: str, myself: dict):
    name = JiraClient.check_user(myself.get('name') or '')
    display_name = myself.get('displayName') or name
    state.creds['jira_token'] = token
    state.jira_user = f'{name} | {display_name}'
    state.jira_display_name = display_name


def restore_jira(state, email: str, user_token: str | None):
    """Restore once per memory session, with a short backoff for service failures."""
    if not user_token or cipher() is None:
        return
    with state.credential_lock:
        if state.creds.get('jira_token') or state.jira_restore_checked:
            return
        if time.monotonic() < state.jira_restore_retry_at:
            return
        from jira_agent.runtime import user_client
        try:
            saved = JiraTokenStore(user_client(user_token), email).load()
            if saved is None:
                state.jira_restore_checked = True
                return
            state.jira_saved = True
            myself = JiraClient(CFG['jira']['base_url'], saved['token']).myself()
            set_jira_identity(state, saved['token'], myself)
            state.jira_saved_until = saved['expires_at']
            state.jira_restore_checked = True
            state.jira_connection_message = ''
        except SavedTokenError as exc:
            state.jira_saved = True
            state.jira_restore_checked = True
            state.jira_connection_message = str(exc)
        except JiraError as exc:
            state.jira_restore_checked = exc.status_code in (401, 403)
            state.jira_restore_retry_at = time.monotonic()+30
            state.jira_connection_message = ('The saved Jira token was rejected. Reconnect or forget it.'
                if state.jira_restore_checked else 'Jira is unavailable. The saved connection will be retried shortly.')
        except Exception:
            state.jira_restore_retry_at = time.monotonic()+30
            state.jira_connection_message = 'The saved Jira connection could not be restored. Please try again shortly.'
