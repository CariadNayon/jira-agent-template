"""The fast default follows the template; explicit user overrides are preserved until reset."""
from fastapi import FastAPI
from fastapi.testclient import TestClient

from jira_agent import CFG
from jira_agent.runtime import DEFAULT_SETTINGS
from jira_agent.state import logout, user_state
from jira_agent.web import install


def test_effective_model_and_empty_override_follow_template_default():
    owner = 'model-defaults@example.test'
    logout(owner)
    user_state(owner).settings = dict(DEFAULT_SETTINGS)
    user_state(owner).skills = {}
    app = FastAPI(); install(app)
    try:
        with TestClient(app, headers={'x-forwarded-email': owner}) as client:
            status = client.get('/jira/api/me').json()
            assert CFG['llm']['deployment'] == status['effective_deployment'] == 'gpt-4.1-mini'
            assert status['defaults']['detailed_deployment'] == 'gpt-4.1'
            client.post('/jira/api/settings', json={'azure_deployment': 'gpt-4o-2'})
            assert client.get('/jira/api/me').json()['effective_deployment'] == 'gpt-4o-2'
            client.post('/jira/api/settings', json={'azure_deployment': ''})
            status = client.get('/jira/api/me').json()
            assert status['effective_deployment'] == 'gpt-4.1-mini'
            assert status['settings']['azure_deployment'] == ''
    finally:
        logout(owner)
