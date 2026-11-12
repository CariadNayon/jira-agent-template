import asyncio
import base64
import io
import json

import httpx
import pytest
from PIL import Image,ImageDraw
from mlflow.types.responses import ResponsesAgentResponse

from agent_server.history import public_output_item
from jira_agent.adapter import RunContext, _on_invoke, available_tools
from jira_agent.state import UploadSink, logout
from jira_agent.testing import FakeFiles,run_tool
from jira_agent.tools import ToolContext,load_tools
from jira_agent.visual_output import VisualResult

EMAIL='pdf-test@example.test'


def scan(pages=4):
    images=[]
    for n in range(pages):
        image=Image.new('RGB',(300,400),'white')
        draw=ImageDraw.Draw(image);draw.rectangle((30,30,120,100),fill=(20+n*40,100,200))
        draw.text((25,150),f'Test scan page {n+1}',fill='black')
        images.append(image)
    out=io.BytesIO();images[0].save(out,format='PDF',save_all=True,append_images=images[1:])
    return out.getvalue()


@pytest.fixture()
def uploaded():
    logout(EMAIL)
    sink=UploadSink(EMAIL,conversation_id='chat-pdf')
    fid=sink.put('scan.pdf','application/pdf',scan())
    return sink,fid


def test_scan_pages_render_with_pagination_and_preview_links(uploaded):
    sink,fid=uploaded
    result=run_tool('read_pdf_pages',uploads=sink,files=FakeFiles(),vision=True,file_id=fid,max_pages=3)
    assert isinstance(result,VisualResult)
    assert result.metadata['next_page']==4 and result.metadata['seiten']==4
    assert [image.page for image in result.images]==[1,2,3]
    for image in result.images:
        with Image.open(io.BytesIO(image.data)) as decoded:
            assert max(decoded.size)<=1800
            assert decoded.convert('RGB').getpixel((100,100)) != (255,255,255)
    last=run_tool('read_pdf_pages',uploads=sink,files=FakeFiles(),vision=True,file_id=fid,start_page=4)
    assert last.metadata['next_page'] is None and len(last.images)==1


def test_visual_pdf_tool_is_hidden_without_vision_and_rejects_wrong_scope(uploaded):
    sink,fid=uploaded
    assert 'read_pdf_pages' not in {t.name for t in available_tools(ToolContext(uploads=sink,files=FakeFiles()))}
    wrong=UploadSink(EMAIL,conversation_id='other-chat',file_ids={fid})
    assert run_tool('read_pdf_pages',uploads=wrong,files=FakeFiles(),vision=True,file_id=fid)['error']=='ValueError'
    assert run_tool('read_pdf_pages',uploads=sink,files=FakeFiles(),file_id=fid)['error']=='ValueError'


def test_visual_page_budget_is_shared_across_calls_in_one_run(uploaded):
    sink,fid=uploaded
    ctx=ToolContext(uploads=sink,files=FakeFiles(),vision=True)
    tool=load_tools()['read_pdf_pages']
    rc=RunContext(ctx,b'test','')
    from jira_agent.adapter import execute
    assert isinstance(execute(tool,rc,{'file_id':fid,'max_pages':3}),VisualResult)
    assert isinstance(execute(tool,rc,{'file_id':fid,'max_pages':3}),VisualResult)
    result=execute(tool,rc,{'file_id':fid,'max_pages':1})
    assert result['error']=='ValueError' and 'höchstens 6' in result['details']


@pytest.mark.parametrize('stream',[False,True])
def test_actual_sdk_delivers_rendered_pages_to_model_but_not_browser_history(uploaded,monkeypatch,stream):
    from agents import Runner,OpenAIChatCompletionsModel
    from jira_agent.model_input import make_run_config
    from openai import AsyncAzureOpenAI
    import jira_agent.runtime as runtime

    sink,fid=uploaded
    captured=[]
    def handle(request):
        body=json.loads(request.content);captured.append(body)
        first=len(captured)==1
        args=json.dumps({'file_id':fid,'max_pages':1})
        if body.get('stream'):
            delta={'role':'assistant','tool_calls':[{'index':0,'id':'call_pdf','type':'function',
                   'function':{'name':'read_pdf_pages','arguments':args}}]} if first else {'role':'assistant','content':'Seite 1 geprüft'}
            chunks=[{'id':'test','object':'chat.completion.chunk','created':0,'model':'vision',
                     'choices':[{'index':0,'delta':delta,'finish_reason':None}]},
                    {'id':'test','object':'chat.completion.chunk','created':0,'model':'vision',
                     'choices':[{'index':0,'delta':{},'finish_reason':'tool_calls' if first else 'stop'}]}]
            return httpx.Response(200,headers={'content-type':'text/event-stream'},
                content=''.join('data: '+json.dumps(x)+'\n\n' for x in chunks)+'data: [DONE]\n\n')
        message={'role':'assistant','content':None,'tool_calls':[{'id':'call_pdf','type':'function',
                 'function':{'name':'read_pdf_pages','arguments':args}}]} if first else {'role':'assistant','content':'Seite 1 geprüft'}
        return httpx.Response(200,json={'id':'test','object':'chat.completion','created':0,'model':'vision',
            'choices':[{'index':0,'message':message,'finish_reason':'tool_calls' if first else 'stop'}],
            'usage':{'prompt_tokens':1,'completion_tokens':1,'total_tokens':2}})
    async def check():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as http:
            client=AsyncAzureOpenAI(api_key='test-only',azure_endpoint='https://example.openai.azure.com',
                                   api_version='2024-12-01-preview',http_client=http,max_retries=0)
            model=OpenAIChatCompletionsModel(model='vision',openai_client=client)
            monkeypatch.setattr(runtime,'build_model',lambda *a:model)
            monkeypatch.setitem(runtime.CFG['agent'],'enabled_tools',['read_pdf_pages'])
            messages=[{'role':'user','content':f'Lies die erste Seite [Datei: scan.pdf](/jira/uploads/{fid})'}]
            agent,ctx=runtime.prepare({'x-forwarded-email':EMAIL},messages,'chat-pdf')
            options=dict(context=ctx,run_config=make_run_config(tracing_disabled=True))
            if stream:
                from agent_server.utils import process_agent_stream_events
                result=Runner.run_streamed(agent,messages,**options)
                events=[e async for e in process_agent_stream_events(result.stream_events())]
                assert 'data:image/png;base64,' not in str(events)
            else:result=await Runner.run(agent,messages,**options)
            assert result.final_output=='Seite 1 geprüft'
            public=[public_output_item(i.to_input_item()) for i in result.new_items]
            assert 'data:image/png;base64,' not in json.dumps(public)
            response=ResponsesAgentResponse(output=public)
            assert response.output
    asyncio.run(check())
    assert len(captured)==2
    image_parts=[p for m in captured[1]['messages'] if isinstance(m.get('content'),list)
                 for p in m['content'] if p.get('type')=='image_url']
    assert len(image_parts)==1, [(m.get('role'),str(m.get('content'))[:350]) for m in captured[1]['messages']]
    assert base64.b64decode(image_parts[0]['image_url']['url'].split(',',1)[1]).startswith(b'\x89PNG')


def test_large_page_png_falls_back_to_jpeg_with_bounded_output(uploaded,monkeypatch):
    import random
    sink,_=uploaded
    rng=random.Random(42)
    image=Image.frombytes('RGB',(300,400),rng.randbytes(300*400*3))
    out=io.BytesIO();image.save(out,format='PDF')
    fid=sink.put('photo-scan.pdf','application/pdf',out.getvalue())
    monkeypatch.setattr('jira_agent.tools.pdf_tools._MAX_PAGE_BYTES',250_000)
    result=run_tool('read_pdf_pages',uploads=sink,files=FakeFiles(),vision=True,file_id=fid)
    assert isinstance(result,VisualResult)
    assert result.images[0].mime=='image/jpeg'
    assert len(result.images[0].data)<=250_000


def test_model_filter_preserves_all_parallel_tool_results_before_images():
    from agents.run_config import ModelInputData,CallModelData
    from jira_agent.model_input import vision_tool_inputs
    original=[{'type':'function_call_output','call_id':'one','output':[
        {'type':'input_text','text':'{"page":1}'},
        {'type':'input_image','image_url':'data:image/png;base64,TEST'}]},
        {'type':'function_call_output','call_id':'two','output':'other tool result'}]
    filtered=vision_tool_inputs(CallModelData(model_data=ModelInputData(input=original,instructions='Rules'),agent=None,context=None))
    assert [x.get('call_id') for x in filtered.input[:2]]==['one','two']
    assert filtered.input[-1]['role']=='user'
    assert filtered.instructions=='Rules'
    assert isinstance(original[0]['output'],list)  # no mutation of canonical tool history
