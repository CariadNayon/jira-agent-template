from jira_agent.jira_client import JiraClient


def test_update_fields_accepts_component_and_priority_names():
    sent = []
    client = JiraClient('https://jira.example.com', 'fixture-token')
    client._call = lambda method, path, **kw: sent.append((method, path, kw["json"]))
    client.update_fields('ABC-1', components=['Car2Phone', {'id': '1'}], priority='High', labels=['x'])
    assert sent == [('PUT', '/issue/ABC-1', {'fields': {
        'components': [{'name': 'Car2Phone'}, {'id': '1'}], 'priority': {'name': 'High'}, 'labels': ['x']}})]
