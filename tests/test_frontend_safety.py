"""Execute the patched stream reader against transport failures and partial tool results."""
import json
import shutil
import subprocess

import pytest

from scripts.frontend_safety import _SIGNATURE, ensure_frontend_safety

ORIGINAL = _SIGNATURE + """
  const reader = uiStream.getReader();
  let receivedTextChunk = false;
  try { return { failed: true }; }
  finally { reader.releaseLock(); }
}
// rest of upstream module
"""


def frontend(tmp_path):
    route = tmp_path / 'server/src/routes/chat.ts'
    fallback = tmp_path / 'server/src/lib/stream-fallback.ts'
    route.parent.mkdir(parents=True)
    fallback.parent.mkdir(parents=True)
    route.write_text('    const result = streamText({\n      model,\n    });\n')
    fallback.write_text(ORIGINAL)
    return route, fallback


@pytest.mark.parametrize('chunks,throw_after,expect_error', [
    ([{'type':'error','errorText':'before text'}], False, True),
    ([{'type':'tool-output-available','output':{'status':'OK'}}, {'type':'error','errorText':'after write'}], False, True),
    ([{'type':'text-delta','delta':'Hello'}, {'type':'error','errorText':'mid-text'}], False, True),
    ([{'type':'text-delta','delta':'Hello'}, {'type':'finish'}], False, False),
    ([], True, True),
    ([{'type':'tool-output-available','output':{'status':'OK'}}], True, True),
])
def test_stream_reader_preserves_chunks_without_replay(tmp_path, chunks, throw_after, expect_error):
    route, fallback = frontend(tmp_path)
    ensure_frontend_safety(tmp_path)
    assert 'maxRetries: 0' in route.read_text()
    text = fallback.read_text()
    # Strip only the TS function signature. Execute the actual patched function body with Node streams.
    end = text.index('\n}\n') + 3
    code = text[:end].replace(_SIGNATURE, 'async function drainStreamToWriter(uiStream, writer) {')
    node = shutil.which('node')
    if not node:
        pytest.skip('Node required for stream integration test')
    program = code + '\n' + f'const chunks={json.dumps(chunks)}; const throwAfter={json.dumps(throw_after)};' + """
const written=[];
const uiStream=new ReadableStream({start(c){
  for(const chunk of chunks)c.enqueue(chunk);
  if(throwAfter) { /* fail on the next read, after queued tool results */ }
  else c.close();
},pull(c){if(throwAfter)c.error(new Error('disconnect'));}});
drainStreamToWriter(uiStream,{write:x=>written.push(x)}).then(result=>{
  process.stdout.write(JSON.stringify({result,written}));
});
"""
    r = subprocess.run([node, '-e', program], capture_output=True, text=True, check=True)
    result = json.loads(r.stdout)
    assert result['result']['failed'] is False
    if expect_error:
        assert result['written'][-1]['type'] == 'data-error'
    expected = [x for x in chunks if x['type'] != 'error']
    assert (result['written'][:-1] if expect_error else result['written']) == expected


def test_patch_is_idempotent_and_preserves_other_upstream_functions(tmp_path):
    route, fallback = frontend(tmp_path)
    ensure_frontend_safety(tmp_path)
    patched = (route.read_text(), fallback.read_text())
    ensure_frontend_safety(tmp_path)
    assert (route.read_text(), fallback.read_text()) == patched
    assert '// rest of upstream module' in fallback.read_text()


def test_changed_upstream_fails_before_any_file_is_written(tmp_path):
    route, fallback = frontend(tmp_path)
    before = route.read_text()
    fallback.write_text('export function different() {}')
    with pytest.raises(RuntimeError, match='Streaming-Ausweichpfad'):
        ensure_frontend_safety(tmp_path)
    assert route.read_text() == before
