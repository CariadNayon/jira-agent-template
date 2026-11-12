"""Regression coverage for the upstream frontend's lost email header."""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from scripts.frontend_identity import ensure_frontend_identity

# Both streamText and the generateText fallback use this object upstream.
ROUTE = """    const requestHeaders = {
      'x-databricks-user-id': session.user.email,
      ...(req.headers['x-forwarded-access-token']
        ? { 'x-forwarded-access-token': req.headers['x-forwarded-access-token'] as string }
        : {}),
    };
"""


def _route(tmp_path, source=ROUTE):
    p = tmp_path / 'server/src/routes/chat.ts'
    p.parent.mkdir(parents=True)
    p.write_text(source)
    return p


@pytest.mark.parametrize('email', ['alice@example.test', 'bob@example.test', None])
def test_forwarded_identity_is_header_only(tmp_path, email):
    route = _route(tmp_path)
    ensure_frontend_identity(tmp_path)
    node = shutil.which('node')
    if not node:
        pytest.skip('Node required to execute frontend header construction')
    # Execute the patched header object, removing only TS type assertions.
    code = route.read_text().replace(' as string', '')
    incoming = {'x-forwarded-access-token': 'obo-test'}
    if email:
        incoming['x-forwarded-email'] = email
    result = subprocess.run([node, '-e',
        'const req = ' + json.dumps({'headers': incoming}) + ';'
        'const session = {user:{email:"untrusted-context@example.test"}};'
        + code + 'process.stdout.write(JSON.stringify(requestHeaders));'],
        capture_output=True, text=True, check=True)
    headers = json.loads(result.stdout)
    assert headers.get('x-forwarded-email') == email
    assert headers['x-forwarded-access-token'] == 'obo-test'


def test_patch_is_idempotent_on_existing_checkout(tmp_path):
    route = _route(tmp_path)
    ensure_frontend_identity(tmp_path)
    patched = route.read_text()
    ensure_frontend_identity(tmp_path)
    assert route.read_text() == patched


def test_upstream_change_fails_before_build(tmp_path):
    route = _route(tmp_path, 'const changed = {};')
    with pytest.raises(RuntimeError, match='Nutzerweitergabe'):
        ensure_frontend_identity(tmp_path)
    assert route.read_text() == 'const changed = {};'
