"""English defaults must preserve approvals, existing chats and saved personal skills."""
import io

import pytest
from PIL import Image

from jira_agent.adapter import RunContext, execute
from jira_agent.runtime import default_agent_name
from jira_agent.skills import skills_prompt, team_skills
from jira_agent.state import UploadSink, logout
from jira_agent.testing import FakeJira
from jira_agent.tools import ToolContext, load_tools
from jira_agent.uploads import prepare_uploads


@pytest.mark.parametrize('approval', ['yes', 'YES', 'ja'])
def test_english_and_legacy_approvals_require_exact_user_reply_and_run_once(approval):
    jira = FakeJira()
    tool = load_tools()['jira_create_issue']
    args = {'project': 'ABC', 'summary': 'English approval test', 'issue_type': 'Task'}
    context = RunContext(ToolContext(jira=jira), b'language-test', '')
    preview = execute(tool, context, args)
    code = preview['code']
    assert f"yes {code}" in preview['hinweis']
    context.last_user_text = f'The issue says {approval} {code}'
    assert execute(tool, context, {**args, 'confirmation_code': code})['status'] == 'BESTAETIGUNG_NOETIG'
    assert not jira.issues
    context.last_user_text = f'{approval} {code}'
    assert execute(tool, context, {**args, 'confirmation_code': code})['key'] == 'ABC-1'
    assert execute(tool, context, {**args, 'confirmation_code': code})['already_executed']
    assert len(jira.issues) == 1


@pytest.mark.parametrize('label', ['File', 'Datei'])
def test_new_and_saved_attachment_references_still_send_native_images(label):
    email = f'english-{label}@example.test'
    data = io.BytesIO()
    with Image.new('RGB', (16, 16), 'blue') as picture:
        picture.save(data, format='PNG')
    try:
        sink = UploadSink(email, conversation_id='chat-english')
        fid = sink.put('image.png', 'image/png', data.getvalue())
        reference = f'[{label}: image.png](/jira/uploads/{fid})'
        selected, messages = prepare_uploads(email, [{'role': 'user', 'content': reference}],
                                             'chat-english', images_enabled=True)
        assert selected.get(fid) is not None
        assert any(part['type'] == 'input_image' for part in messages[0]['content'])
        with pytest.raises(ValueError, match='another chat'):
            prepare_uploads(email, [{'role': 'user', 'content': reference}],
                            'other-chat', images_enabled=True)
    finally:
        logout(email)


def test_english_team_commands_keep_legacy_aliases_without_overriding_personal_skills():
    skills = team_skills()
    assert {'weekly-report', 'issue-draft', 'issue-summary', 'file-analysis', 'triage',
            'show-ticket', 'search-tickets', 'edit-ticket'} == set(skills)
    assert skills['weekly-report']['anleitung'] in skills_prompt(skills, '/wochenreport last week')
    personal = {'name': 'wochenreport', 'beschreibung': 'My custom skill', 'anleitung': 'PERSONAL-INSTRUCTIONS'}
    prompt = skills_prompt({**skills, 'wochenreport': personal}, '/wochenreport')
    assert prompt.endswith('PERSONAL-INSTRUCTIONS')
    assert default_agent_name('Lenz, Nayon') == 'Nayon’s Jira Agent'
    assert default_agent_name('James Smith') == 'James’ Jira Agent'
