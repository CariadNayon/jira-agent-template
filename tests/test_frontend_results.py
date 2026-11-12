import json
import shutil
import subprocess

import pytest
from scripts.frontend_results import _ANCHOR,ensure_frontend_results


@pytest.mark.parametrize('output,expected',[
    ({'error':'ValueError','details':'PNG cannot be read'},'output-error'),
    (json.dumps({'error':'JiraError','details':'HTTP 403'}),'output-error'),
    ({'status':'BESTAETIGUNG_NOETIG','code':'ABC123'},'approval-requested'),
    ({'status':'AKTION_LAEUFT'},'input-available'),
    ({'status':'RESULT_TOO_LARGE'},'output-error'),
    ({'outcome':'unverified'},'output-error'),
    ({'status':'OK'},'output-available'),
    ('ordinary non-JSON result','output-available'),
])
def test_tool_badge_reflects_actual_application_result(tmp_path,output,expected):
    file=tmp_path/'client/src/components/message.tsx'
    file.parent.mkdir(parents=True)
    file.write_text(_ANCHOR+'    return state;\n  })();\n')
    ensure_frontend_results(tmp_path)
    source=file.read_text();ensure_frontend_results(tmp_path)
    assert file.read_text()==source
    node=shutil.which('node')
    if not node:pytest.skip('Node required for frontend status test')
    script='const output='+json.dumps(output)+"; const state='output-available';const isMcpApproval=false;"
    script+=source.replace(': ToolState','').replace(': any','')
    script+='process.stdout.write(JSON.stringify(effectiveState));'
    result=subprocess.run([node,'-e',script],capture_output=True,text=True,check=True)
    assert json.loads(result.stdout)==expected


def test_unknown_frontend_state_handler_fails_before_build(tmp_path):
    file=tmp_path/'client/src/components/message.tsx';file.parent.mkdir(parents=True)
    file.write_text('unknown renderer')
    with pytest.raises(RuntimeError,match='Tool-Ergebnisstatus'):ensure_frontend_results(tmp_path)
    assert file.read_text()=='unknown renderer'
