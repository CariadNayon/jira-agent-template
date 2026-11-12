"""Upload -> chat-scoped reference -> actual Agents SDK -> mocked Azure HTTP request."""
import asyncio
import base64
import io
import json
import time

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image

from jira_agent import CFG
from jira_agent.state import UploadSink, logout
from jira_agent.uploads import image_info, prepare_uploads
from jira_agent.web import install

EMAIL = 'image-tests@example.test'


def picture(fmt='PNG'):
    out = io.BytesIO()
    Image.new('RGB', (24, 16), (20, 100, 200)).save(out, format=fmt)
    return out.getvalue()


@pytest.fixture()
def client():
    logout(EMAIL)
    app = FastAPI()
    install(app)
    return TestClient(app, headers={'x-forwarded-email': EMAIL})


def upload(client, name='image.png', chat='chat-a', data=None):
    r = client.post('/jira/api/upload', params={'name':name,'chat_id':chat},
                    content=picture() if data is None else data,
                    headers={'content-type':'application/octet-stream'})
    assert r.status_code == 200, r.text
    return r.json()


def test_image_is_validated_and_converted_to_native_input_image(client):
    data = picture()
    f = upload(client,data=data)
    messages = [{'role':'user','content':'Was siehst du? '+f['reference']}]
    sink, prepared = prepare_uploads(EMAIL,messages,'chat-a',images_enabled=True)
    part = next(p for p in prepared[0]['content'] if p['type']=='input_image')
    assert part['image_url'].startswith('data:image/png;base64,')
    assert base64.b64decode(part['image_url'].split(',',1)[1]) == data
    assert [x['id'] for x in sink.list()] == [f['id']]
    assert messages[0]['content'].startswith('Was siehst du?')  # caller input not overwritten here
    assert client.get('/jira/uploads/'+f['id']).content == data
    assert client.get('/jira/uploads/'+f['id'],headers={'x-forwarded-email':'other@example.test'}).status_code == 404


@pytest.mark.parametrize('name,data', [('image.png',b'not an image'), ('bad.svg',b'<svg/>'),
                                      ('bad.gif',b'GIF89a'), ('bad.docx',b'PK'),
                                      ('wrong.png',picture('JPEG'))])
def test_upload_rejects_bad_or_unsupported_content_before_storage(client,name,data):
    r=client.post('/jira/api/upload?name='+name,content=data)
    assert r.status_code == 415
    assert not UploadSink(EMAIL).list()


def test_image_size_dimensions_and_disabled_model_are_explicit(client,monkeypatch):
    r=client.post('/jira/api/upload?name=large.png',content=b'x'*(5*1024*1024+1))
    assert r.status_code == 415 and '5 MB' in r.text
    monkeypatch.setattr('jira_agent.uploads._MAX_IMAGE_PIXELS',100)
    assert client.post('/jira/api/upload?name=pixels.png',content=picture()).status_code == 415
    monkeypatch.setitem(CFG['llm'],'supports_images',False)
    r=client.post('/jira/api/upload?name=image.png',content=picture())
    assert r.status_code == 415 and 'deaktiviert' in r.text


@pytest.mark.parametrize('ext,fmt,mime',[('png','PNG','image/png'),('jpg','JPEG','image/jpeg'),('webp','WEBP','image/webp')])
def test_supported_image_formats(client,ext,fmt,mime):
    f=upload(client,name='image.'+ext,data=picture(fmt))
    assert f['mime'] == mime
    assert image_info('image.'+ext,picture(fmt))['width'] == 24


def test_chat_reference_selects_exact_file_among_identical_names(client):
    a=upload(client)
    b=upload(client)
    other=upload(client,chat='chat-b')
    sink,_=prepare_uploads(EMAIL,[{'role':'user','content':a['reference']}],'chat-a',images_enabled=True)
    assert sink.get(a['id']) is not None
    assert sink.get(b['id']) is None
    assert sink.get(other['id']) is None
    with pytest.raises(ValueError,match='anderen Chat'):
        prepare_uploads(EMAIL,[{'role':'user','content':a['reference']}],'chat-b',images_enabled=True)
    with pytest.raises(ValueError,match='nicht eindeutig'):
        prepare_uploads(EMAIL,[{'role':'user','content':'[Datei: image.png]'}],'chat-a',images_enabled=True)


def test_tool_outputs_and_assistant_messages_cannot_attach_images(client):
    f=upload(client)
    for role in ['assistant','tool']:
        sink,prepared=prepare_uploads(EMAIL,[{'role':role,'content':f['reference']}],'chat-a',images_enabled=True)
        assert not sink.list()
        assert isinstance(prepared[0]['content'],str)


def test_followup_keeps_image_but_does_not_duplicate_payload(client):
    f=upload(client)
    sink,prepared=prepare_uploads(EMAIL,[{'role':'user','content':f['reference']},
        {'role':'assistant','content':'Antwort'}, {'role':'user','content':'Was ist oben rechts?'}],'chat-a',images_enabled=True)
    assert any(p['type']=='input_image' for p in prepared[0]['content'])
    _,repeated=prepare_uploads(EMAIL,[{'role':'user','content':f['reference']},
        {'role':'user','content':f['reference']}],'chat-a',images_enabled=True)
    assert sum(p['type']=='input_image' for m in repeated for p in m['content'] if isinstance(p,dict)) == 1


def test_expiry_and_wrong_owner_never_send_image_bytes(client):
    f=upload(client)
    stored=UploadSink(EMAIL).get(f['id'])
    with pytest.raises(ValueError,match='Anhang fehlt'):
        prepare_uploads('other@example.test',[{'role':'user','content':f['reference']}],'chat-a',images_enabled=True)
    stored.created=time.time()-3601
    with pytest.raises(ValueError,match='abgelaufen'):
        prepare_uploads(EMAIL,[{'role':'user','content':f['reference']}],'chat-a',images_enabled=True)
    _,history=prepare_uploads(EMAIL,[{'role':'user','content':f['reference']},
        {'role':'user','content':'Neue Frage'}],'chat-a',images_enabled=True)
    assert not any(p.get('type')=='input_image' for p in history[0]['content'])


def test_api_upload_binds_on_first_explicit_use_and_requires_chat_id(client):
    f=client.post('/jira/api/upload?name=image.png',content=picture()).json()
    with pytest.raises(ValueError,match='Gesprächskennung'):
        prepare_uploads(EMAIL,[{'role':'user','content':f['reference']}],'',images_enabled=True)
    prepare_uploads(EMAIL,[{'role':'user','content':f['reference']}],'chat-a',images_enabled=True)
    assert UploadSink(EMAIL).get(f['id']).conversation_id == 'chat-a'
    with pytest.raises(ValueError,match='anderen Chat'):
        prepare_uploads(EMAIL,[{'role':'user','content':f['reference']}],'chat-b',images_enabled=True)


def test_image_tool_returns_metadata_not_base64_text(client):
    from jira_agent.testing import run_tool
    f=upload(client)
    result=run_tool('read_uploaded_file',uploads=UploadSink(EMAIL,conversation_id='chat-a',file_ids={f['id']}),file_id=f['id'])
    assert result == {'name':'image.png','type':'image','mime':'image/png','width':24,'height':16}
    assert 'base64' not in json.dumps(result)


@pytest.mark.parametrize('stream',[False,True])
def test_real_sdk_sends_image_to_azure_for_both_agent_paths(client,monkeypatch,stream):
    from agents import Runner, RunConfig, OpenAIChatCompletionsModel
    from openai import AsyncAzureOpenAI
    import jira_agent.runtime as runtime

    f=upload(client)
    captured=[]
    def handle(request):
        body=json.loads(request.content)
        captured.append(body)
        if body.get('stream'):
            chunks=[{'id':'test','object':'chat.completion.chunk','created':0,'model':'vision',
                     'choices':[{'index':0,'delta':{'role':'assistant','content':'Simulierte Antwort'},'finish_reason':None}]},
                    {'id':'test','object':'chat.completion.chunk','created':0,'model':'vision',
                     'choices':[{'index':0,'delta':{},'finish_reason':'stop'}]}]
            data=''.join('data: '+json.dumps(x)+'\n\n' for x in chunks)+'data: [DONE]\n\n'
            return httpx.Response(200,headers={'content-type':'text/event-stream'},content=data)
        return httpx.Response(200,json={'id':'test','object':'chat.completion','created':0,'model':'vision',
            'choices':[{'index':0,'message':{'role':'assistant','content':'Simulierte Antwort'},'finish_reason':'stop'}],
            'usage':{'prompt_tokens':1,'completion_tokens':1,'total_tokens':2}})
    async def check():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as http:
            azure=AsyncAzureOpenAI(api_key='test-only',azure_endpoint='https://example.openai.azure.com',
                                   api_version='2024-12-01-preview',http_client=http,max_retries=0)
            model=OpenAIChatCompletionsModel(model='vision',openai_client=azure)
            monkeypatch.setattr(runtime,'build_model',lambda *a:model)
            messages=[{'role':'user','content':'Was siehst du? '+f['reference']}]
            agent,ctx=runtime.prepare({'x-forwarded-email':EMAIL},messages,'chat-a')
            options=dict(context=ctx,run_config=RunConfig(tracing_disabled=True))
            if stream:
                result=Runner.run_streamed(agent,messages,**options)
                async for _ in result.stream_events(): pass
            else:
                result=await Runner.run(agent,messages,**options)
            assert result.final_output == 'Simulierte Antwort'
    asyncio.run(check())
    user=next(m for m in captured[0]['messages'] if m['role']=='user')
    image=next(p for p in user['content'] if p['type']=='image_url')
    assert base64.b64decode(image['image_url']['url'].split(',',1)[1]) == picture()


def test_current_message_image_limits_are_not_silently_truncated(client,monkeypatch):
    files=[upload(client,name=f'image-{n}.png') for n in range(5)]
    messages=[{'role':'user','content':' '.join(f['reference'] for f in files)}]
    with pytest.raises(ValueError,match='höchstens 4'):
        prepare_uploads(EMAIL,messages,'chat-a',images_enabled=True)
    monkeypatch.setattr('jira_agent.uploads._MAX_IMAGE_TOTAL',len(picture())+1)
    with pytest.raises(ValueError,match='10 MB'):
        prepare_uploads(EMAIL,[{'role':'user','content':' '.join(f['reference'] for f in files[:2])}],
                        'chat-a',images_enabled=True)


def test_truncated_jpeg_is_rejected_not_forwarded_to_model(client):
    data=picture('JPEG')
    r=client.post('/jira/api/upload?name=truncated.jpg',content=data[:-20])
    assert r.status_code == 415
    assert not UploadSink(EMAIL).list()
