"""A report must not claim coverage for missing tests or hide failed parametrizations."""
import json
from types import SimpleNamespace
import xml.etree.ElementTree as ET

import pytest

from agent_server.stability import percentile, report_cases


def test_report_matches_actual_tests_and_keeps_failed_or_skipped_parameters():
    root = ET.fromstring('''<testsuites><testsuite>
      <testcase classname="tests.example" name="test_case[one]" time="0.1"/>
      <testcase classname="tests.example" name="test_case[two]" time="0.2"><failure/></testcase>
      <testcase classname="tests.example" name="test_case[three]" time="0.3"><skipped/></testcase>
      <testcase classname="tests.example_other" name="test_case" time="1"/>
    </testsuite></testsuites>''')
    cases = report_cases(root, 'tests/example.py::test_case')
    assert [c['status'] for c in cases] == ['passed', 'failure', 'skipped']
    assert report_cases(root, 'tests/example.py::test_missing') == []
    assert percentile([10, 20, 30, 40], 0.5) == 20
    assert percentile([10, 20, 30, 40], 0.95) == 40


def test_live_comparison_uses_requested_deployments_and_fresh_clients_for_turns(monkeypatch, tmp_path):
    import agent_server.evaluate_agent as command
    import agent_server.evaluation as evaluation
    import jira_agent.llm as llm
    created, closed, observed = [], [], []
    class Client:
        async def close(self): closed.append(id(self))
    def build(provider, cfg, settings, creds):
        model = SimpleNamespace(_jira_agent_client=Client(), deployment=settings['azure_deployment'])
        created.append(model)
        return model
    async def run(case, model, model_factory=None):
        first, second = model_factory(), model_factory()
        assert first is not second and first.deployment == second.deployment == model.deployment
        observed.append((case, model.deployment))
        await first._jira_agent_client.close(); await second._jira_agent_client.close()
        return {'case': case, 'passed': True, 'seconds': 1, 'tools': [], 'metrics': {}}
    monkeypatch.setattr(llm, 'build_model', build)
    monkeypatch.setattr(evaluation, 'run_case', run)
    output = tmp_path / 'report.json'
    monkeypatch.setattr('sys.argv', ['agent-evaluate', '--live', '--case', 'jira_search', '--repeat', '2',
        '--deployment', 'first', '--deployment', 'second', '--json-report', str(output)])
    with pytest.raises(SystemExit) as status:
        command.evaluate()
    assert status.value.code == 0
    report = json.loads(output.read_text())
    assert report['passed'] and report['summary']['first']['runs'] == report['summary']['second']['runs'] == 2
    assert observed == [('jira_search', 'first')]*2 + [('jira_search', 'second')]*2
    assert len(created) == len(closed) == 10
