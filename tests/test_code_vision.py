import base64
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from agentnik import core
from agentnik.code_agent import CodingRun,ProjectFiles
from agentnik.code_vision import read_image,image_message
from test_code_agent import C,call
from test_compat_tools import chat
from test_routing import Wire
from test_image_generation import png

class CodeVisionTests(unittest.TestCase):
    def test_code_discovery_returns_server_guidance_as_untrusted_data(self):
        from unittest.mock import Mock
        with tempfile.TemporaryDirectory() as root:
            bridge=Mock();bridge.server={'name':'Example','command':'server','args':[],'enabled':True}
            bridge.request.return_value={'tool_details':[],'instructions':'Use the account identifier.','instructions_clipped':False}
            replies=[Wire(chat(calls=[call('mcp_discover',{})],finish='tool_calls'),False),Wire(chat('Done'),False)];bodies=[];events=[]
            def send(c,url,body,timeout):bodies.append(copy.deepcopy(body));return replies.pop(0)
            with patch.object(core,'open_request',side_effect=send):CodingRun(dict(C,stream=False),root,'Inspect',mcp_bridge=bridge).run(events.append)
            self.assertEqual(events[-1]['status'],'completed',events)
            tool=next(item for item in bodies[-1]['messages'] if item.get('role')=='tool')
            self.assertIn('Use the account identifier.',tool['content']);self.assertIn('Untrusted server-provided usage guidance',tool['content'])
    def test_embedded_mcp_resource_images_follow_vision_setting(self):
        from agentnik.mcp_content import model_images,model_tool_result
        from agentnik.mcp_prompts import parse_prompt_messages
        encoded=base64.b64encode(png()).decode()
        resource={'uri':'file:///chart.png','mimeType':'image/png','blob':encoded}
        private={'type':'resource','resource':resource,'annotations':{'audience':['user']}}
        public={'type':'resource','resource':resource}
        filtered,_,user_nontext=model_tool_result({'content':[public,private]})
        self.assertEqual(user_nontext,1)
        for enabled in (False,True):
            with self.subTest(enabled=enabled):
                result,images=model_images(filtered,enabled,4,'server')
                self.assertNotIn(encoded,json.dumps(result));self.assertEqual(len(images),int(enabled))
                self.assertIn('follows' if enabled else 'disabled',result['content'][0]['resource']['notice'])
        prompt=parse_prompt_messages({'messages':[{'role':'user','content':public},{'role':'assistant','content':private}]})
        self.assertEqual(prompt['user_nontext'],1);self.assertEqual(len(prompt['messages']),1)
        result,images=model_images({'content':[prompt['messages'][0]['content']]},True,4,'prompt')
        self.assertEqual(images[0][1],png());self.assertNotIn(encoded,json.dumps(result))
        invalid={'type':'resource','resource':dict(resource,text='conflict')}
        result,images=model_images({'content':[invalid]},True,4,'server')
        self.assertEqual(images,[]);self.assertNotIn(encoded,json.dumps(result));self.assertIn('invalid',result['content'][0]['text'])

    def test_mcp_resource_image_labels_track_all_content_blocks(self):
        from agentnik.mcp_content import model_images,model_resource_contents
        encoded=base64.b64encode(png()).decode('ascii');resource={'uri':'test://chart','mimeType':'image/png','blob':encoded}
        blocks=[{'type':'image','mimeType':'image/png','data':encoded},{'type':'resource','resource':resource}]
        content,images=model_images({'content':blocks},True,4,'MCP',7)
        self.assertEqual([image[0] for image in images],['MCP image 8','MCP image 9'])
        self.assertIn('MCP image 8',content['content'][0]['text']);self.assertIn('MCP image 9',content['content'][1]['resource']['notice'])
        contents,images=model_resource_contents([resource,resource],True,4,'MCP',9)
        self.assertEqual([image[0] for image in images],['MCP image 10','MCP image 11'])
        self.assertIn('MCP image 11',contents[1]['notice'])

    def test_mcp_tool_embedded_image_reaches_model_as_visual(self):
        from unittest.mock import Mock
        encoded=base64.b64encode(png()).decode()
        detail={'name':'chart','description':'Chart','description_clipped':False,'schema':{'type':'object'},'schema_status':'available'}
        with tempfile.TemporaryDirectory() as root:
            bridge=Mock();bridge.server={'name':'Charts','command':'server','args':[],'enabled':True}
            bridge.request.side_effect=[{'tool_details':[detail]},{'call_result':{'content':[{'type':'resource','resource':{'uri':'file:///chart','mimeType':'image/png','blob':encoded}}]}}]
            replies=[Wire(chat(calls=[call('mcp_discover',{})],finish='tool_calls'),False),Wire(chat(calls=[call('mcp_call',{'tool':'chart','arguments':'{}'})],finish='tool_calls'),False),Wire(chat('Done'),False)]
            bodies=[];events=[]
            def send(c,url,body,timeout):bodies.append(copy.deepcopy(body));return replies.pop(0)
            with patch.object(core,'open_request',side_effect=send):CodingRun(dict(C,stream=False),root,'Inspect chart',mcp_bridge=bridge,vision_enabled=True).run(events.append)
            self.assertEqual(events[-1]['status'],'completed',events);messages=bodies[-1]['messages']
            tool=next(m for m in reversed(messages) if m['role']=='tool');self.assertNotIn(encoded,tool['content']);self.assertNotIn(encoded,json.dumps(events))
            self.assertEqual(messages[-1]['content'][1]['image_url']['url'],'data:image/png;base64,'+encoded)

    def test_mcp_image_resource_reaches_vision_model(self):
        from unittest.mock import Mock
        encoded=base64.b64encode(png()).decode()
        for enabled in (True,False):
            for templated in (True,False):
                with self.subTest(enabled=enabled,templated=templated),tempfile.TemporaryDirectory() as root:
                    bridge=Mock();bridge.server={'name':'Charts','command':'server','args':[],'enabled':True}
                    resource={'uri':'chart://1','name':'chart','description':'','mimeType':'image/png'}
                    template={'uriTemplate':'chart://{id}','name':'chart','description':'','mimeType':'image/png','supported':True,'variables':['id']}
                    listing={'templates':[template]} if templated else {'resources':[resource]}
                    bridge.request.side_effect=[{'tool_details':[]},listing,{'contents':[{'uri':'chart://1','mimeType':'image/png','blob':encoded}]}]
                    list_name='mcp_list_resource_templates' if templated else 'mcp_list_resources'
                    read_name='mcp_read_resource_template' if templated else 'mcp_read_resource'
                    read_args={'template':'chart://{id}','variables':'{"id":"1"}'} if templated else {'uri':'chart://1'}
                    replies=[Wire(chat(calls=[call('mcp_discover',{})],finish='tool_calls'),False),Wire(chat(calls=[call(list_name,{})],finish='tool_calls'),False),Wire(chat(calls=[call(read_name,read_args)],finish='tool_calls'),False),Wire(chat('Done'),False)]
                    bodies=[];events=[]
                    def send(c,url,body,timeout):bodies.append(copy.deepcopy(body));return replies.pop(0)
                    with patch.object(core,'open_request',side_effect=send):CodingRun(dict(C,stream=False),root,'Inspect chart',mcp_bridge=bridge,vision_enabled=enabled).run(events.append)
                    self.assertEqual(events[-1]['status'],'completed',events);messages=bodies[-1]['messages'];tool=next(m for m in reversed(messages) if m['role']=='tool')
                    self.assertNotIn(encoded,tool['content']);self.assertNotIn(encoded,json.dumps(events))
                    if enabled:self.assertEqual(messages[-1]['content'][1]['image_url']['url'],'data:image/png;base64,'+encoded)
                    else:self.assertIn('inspection is disabled',tool['content']);self.assertNotIn(encoded,json.dumps(messages))

    def test_mcp_prompt_image_is_visual_only_when_enabled(self):
        from unittest.mock import Mock
        from agentnik.mcp_prompts import parse_prompt_messages
        encoded=base64.b64encode(png()).decode()
        prompt={'name':'review','description':'Review image','arguments':[]}
        content={'type':'image','data':encoded,'mimeType':'image/png'}
        prompt_result=parse_prompt_messages({'messages':[{'role':'user','content':content},{'role':'assistant','content':dict(content,annotations={'audience':['user']})}]})
        for enabled in (True,False):
            with self.subTest(enabled=enabled),tempfile.TemporaryDirectory() as root:
                bridge=Mock();bridge.server={'name':'Charts','command':'server','args':[],'enabled':True}
                bridge.request.side_effect=[{'tool_details':[]},{'prompts':[prompt]},prompt_result]
                replies=[Wire(chat(calls=[call('mcp_discover',{})],finish='tool_calls'),False),Wire(chat(calls=[call('mcp_list_prompts',{})],finish='tool_calls'),False),Wire(chat(calls=[call('mcp_get_prompt',{'name':'review','arguments':'{}'})],finish='tool_calls'),False),Wire(chat('Done'),False)]
                bodies=[];events=[]
                def send(c,url,body,timeout):bodies.append(copy.deepcopy(body));return replies.pop(0)
                with patch.object(core,'open_request',side_effect=send):CodingRun(dict(C,stream=False),root,'Review',mcp_bridge=bridge,vision_enabled=enabled).run(events.append)
                self.assertEqual(events[-1]['status'],'completed',events);messages=bodies[-1]['messages']
                tool=next(m for m in reversed(messages) if m['role']=='tool');self.assertNotIn(encoded,tool['content']);self.assertNotIn(encoded,json.dumps(events))
                self.assertTrue(any('user-directed prompt content: 1 non-text' in e.get('text','') for e in events))
                if enabled:self.assertEqual(messages[-1]['content'][1]['image_url']['url'],'data:image/png;base64,'+encoded)
                else:self.assertIn('inspection is disabled',tool['content']);self.assertNotIn(encoded,json.dumps(messages))

    def test_mcp_image_result_is_visual_only_when_enabled(self):
        from unittest.mock import Mock
        encoded=base64.b64encode(png()).decode()
        detail={'name':'chart','description':'Chart','description_clipped':False,'schema':{'type':'object'},'schema_status':'available'}
        for enabled in (True,False):
            with self.subTest(enabled=enabled),tempfile.TemporaryDirectory() as root:
                bridge=Mock();bridge.server={'name':'Charts','command':'server','args':[],'enabled':True}
                bridge.request.side_effect=[{'tool_details':[detail]},{'call_result':{'content':[{'type':'image','data':encoded,'mimeType':'image/png'},{'type':'image','data':encoded,'mimeType':'image/png','annotations':{'audience':['user']}}]}}]
                replies=[Wire(chat(calls=[call('mcp_discover',{})],finish='tool_calls'),False),Wire(chat(calls=[call('mcp_call',{'tool':'chart','arguments':'{}'})],finish='tool_calls'),False),Wire(chat('Done'),False)]
                bodies=[];events=[]
                def send(c,url,body,timeout):bodies.append(copy.deepcopy(body));return replies.pop(0)
                with patch.object(core,'open_request',side_effect=send):CodingRun(dict(C,stream=False),root,'Inspect chart',mcp_bridge=bridge,vision_enabled=enabled).run(events.append)
                self.assertEqual(events[-1]['status'],'completed',events)
                messages=bodies[-1]['messages'];tool=next(m for m in reversed(messages) if m['role']=='tool')
                self.assertNotIn(encoded,tool['content']);self.assertNotIn(encoded,json.dumps(events))
                if enabled:
                    self.assertEqual(messages[-1]['content'][1]['image_url']['url'],'data:image/png;base64,'+encoded)
                    self.assertEqual(len(messages[-1]['content']),2)
                else:self.assertIn('inspection is disabled',tool['content']);self.assertNotIn(encoded,json.dumps(messages))

    def test_mcp_invalid_images_are_not_forwarded(self):
        from agentnik.mcp_content import model_images
        encoded=base64.b64encode(png()).decode()
        result={'content':[{'type':'image','data':'not-base64','mimeType':'image/png'},{'type':'image','data':encoded,'mimeType':'image/jpeg'},{'type':'image','data':encoded,'mimeType':'image/png'}]}
        safe,images=model_images(result,True,1,'MCP chart')
        self.assertEqual(len(images),1);self.assertNotIn(encoded,json.dumps(safe));self.assertIn('invalid',safe['content'][0]['text']);self.assertIn('invalid',safe['content'][1]['text'])
        safe,images=model_images(result,True,0,'MCP chart');self.assertEqual(images,[]);self.assertIn('batch limit',safe['content'][0]['text'])

    def test_code_omits_mcp_images_that_exceed_remaining_context(self):
        from unittest.mock import Mock
        from agentnik.code_limits import coding_limits
        small=png();large=small+b'x'*30000
        blocks=[{'type':'image','data':base64.b64encode(data).decode('ascii'),'mimeType':'image/png'} for data in (large,small)]
        detail={'name':'chart','description':'Chart','description_clipped':False,'schema':{'type':'object'},'schema_status':'available'}
        with tempfile.TemporaryDirectory() as root:
            bridge=Mock();bridge.server={'name':'Charts','command':'server','args':[],'enabled':True}
            bridge.request.side_effect=[{'tool_details':[detail]},{'call_result':{'content':blocks}}]
            replies=[Wire(chat(calls=[call('mcp_discover',{})],finish='tool_calls'),False),Wire(chat(calls=[call('mcp_call',{'tool':'chart','arguments':'{}'})],finish='tool_calls'),False),Wire(chat('Done'),False)]
            limits=coding_limits();limits['context_bytes']=12000;bodies=[];events=[]
            def send(c,url,body,timeout):bodies.append(copy.deepcopy(body));return replies.pop(0)
            with patch.object(core,'open_request',side_effect=send):CodingRun(dict(C,stream=False),root,'Inspect',limits=limits,mcp_bridge=bridge,vision_enabled=True).run(events.append)
            self.assertEqual(events[-1]['status'],'completed',events);model=json.dumps(bodies[-1])
            self.assertIn(base64.b64encode(small).decode('ascii'),model);self.assertNotIn(base64.b64encode(large).decode('ascii'),model)
            self.assertIn('1 image(s) were omitted because the coding run context limit',model)
            visual=bodies[-1]['messages'][-1]['content'][0]['text']
            self.assertIn('MCP image 2',visual);self.assertIn('Omitted image labels: ["MCP image 1"]',visual)
            self.assertTrue(any('1 omitted due to the coding run context limit' in event.get('text','') for event in events))
            self.assertNotIn(base64.b64encode(small).decode('ascii'),json.dumps(events))

    def test_code_mcp_image_labels_are_unique_across_model_rounds(self):
        from unittest.mock import Mock
        encoded=base64.b64encode(png()).decode('ascii');detail={'name':'chart','description':'Chart','description_clipped':False,'schema':{'type':'object'},'schema_status':'available'}
        with tempfile.TemporaryDirectory() as root:
            bridge=Mock();bridge.server={'name':'Charts','command':'server','args':[],'enabled':True}
            result={'call_result':{'content':[{'type':'image','data':encoded,'mimeType':'image/png'}]}}
            bridge.request.side_effect=[{'tool_details':[detail]},result,result]
            calls=[call('mcp_call',{'tool':'chart','arguments':'{}'},'first'),call('mcp_call',{'tool':'chart','arguments':'{}'},'second')]
            replies=[Wire(chat(calls=[call('mcp_discover',{})],finish='tool_calls'),False),*[Wire(chat(calls=[item],finish='tool_calls'),False) for item in calls],Wire(chat('Done'),False)]
            bodies=[];events=[]
            def send(c,url,body,timeout):bodies.append(copy.deepcopy(body));return replies.pop(0)
            with patch.object(core,'open_request',side_effect=send):CodingRun(dict(C,stream=False),root,'Inspect',mcp_bridge=bridge,vision_enabled=True).run(events.append)
            self.assertEqual(events[-1]['status'],'completed',events)
            messages=bodies[-1]['messages'];visual=[item for item in messages if item.get('role')=='user' and isinstance(item.get('content'),list) and any(block.get('type')=='image_url' for block in item['content'])]
            self.assertEqual(len(visual),2);self.assertIn('MCP image 1',visual[0]['content'][0]['text']);self.assertIn('MCP image 2',visual[1]['content'][0]['text'])

    def test_model_receives_image_after_tool_result(self):
        with tempfile.TemporaryDirectory() as root:
            Path(root,'image.png').write_bytes(png());events=[];bodies=[]
            replies=[Wire(chat(calls=[call('view_image',{'path':'image.png'})],finish='tool_calls'),False),Wire(chat('It is red.'),False)]
            def send(c,url,body,timeout):bodies.append(copy.deepcopy(body));return replies.pop(0)
            with patch.object(core,'open_request',side_effect=send):CodingRun(dict(C,stream=False),root,'Inspect',vision_enabled=True).run(events.append)
            self.assertEqual(events[-1]['status'],'completed');self.assertIn('view_image',[x['function']['name'] for x in bodies[0]['tools']])
            self.assertEqual(bodies[1]['messages'][-2]['role'],'tool');block=bodies[1]['messages'][-1]['content'][1]
            self.assertEqual(block['image_url']['url'],'data:image/png;base64,'+base64.b64encode(png()).decode())
            self.assertNotIn(base64.b64encode(png()).decode(),json.dumps(events))

    def test_code_reports_omitted_project_image_and_continues(self):
        from agentnik.code_limits import coding_limits
        with tempfile.TemporaryDirectory() as root:
            data=png()+b'x'*30000;Path(root,'image.png').write_bytes(data)
            replies=[Wire(chat(calls=[call('view_image',{'path':'image.png'})],finish='tool_calls'),False),Wire(chat('I cannot inspect it.'),False)]
            limits=coding_limits();limits['context_bytes']=12000;events=[];bodies=[]
            def send(c,url,body,timeout):bodies.append(copy.deepcopy(body));return replies.pop(0)
            with patch.object(core,'open_request',side_effect=send):CodingRun(dict(C,stream=False),root,'Inspect',limits=limits,vision_enabled=True).run(events.append)
            self.assertEqual(events[-1]['status'],'completed',events)
            self.assertIn('1 image(s) were omitted because the coding run context limit',json.dumps(bodies[-1]))
            self.assertNotIn(base64.b64encode(data).decode('ascii'),json.dumps(bodies[-1]))
            self.assertTrue(any('Sending 0 image(s)' in event.get('text','') for event in events))
    def test_protocol_shapes_and_path_boundaries(self):
        image=[('picture.png',png(),'image/png')]
        self.assertEqual(image_message(image,'responses')['content'][1]['type'],'input_image')
        self.assertEqual(image_message(image,'messages')['content'][1]['source']['media_type'],'image/png')
        self.assertTrue(image_message(image,'chat',True)['images'])
        with tempfile.TemporaryDirectory() as root:
            Path(root,'invalid.png').write_bytes(b'not image')
            for path in ('../secret','.env','invalid.png'):
                with self.assertRaises(ValueError):read_image(ProjectFiles(root),path)
    def test_disabled_tool_is_unavailable(self):
        with tempfile.TemporaryDirectory() as root:
            events=[];bodies=[]
            def send(c,url,body,timeout):bodies.append(copy.deepcopy(body));return Wire(chat('Done'),False)
            with patch.object(core,'open_request',side_effect=send):CodingRun(dict(C,stream=False),root,'Inspect').run(events.append)
            self.assertNotIn('view_image',[x['function']['name'] for x in bodies[0]['tools']])

    def test_subagents_receive_only_approved_image_snapshots(self):
        with tempfile.TemporaryDirectory() as root:
            Path(root,'slide.png').write_bytes(png());events=[];bodies=[]
            tasks=[{'task':'Review slide','images':['slide.png']},{'task':'Review outline'}]
            run=CodingRun(dict(C,stream=False),root,'Review',vision_enabled=True)
            def send(c,url,body,timeout):
                bodies.append(copy.deepcopy(body));messages=body['messages']
                if any(m.get('role')=='tool' for m in messages):return Wire(chat('Reviewed'),False)
                if any(isinstance(m.get('content'),str) and 'Independent read-only coding analysis' in m['content'] for m in messages):return Wire(chat('Looks red'),False)
                return Wire(chat(calls=[call('delegate_subagents',{'tasks':json.dumps(tasks)})],finish='tool_calls'),False)
            def emit(event):
                events.append(event)
                if event['kind']=='operation_proposal':run.decide(event['fingerprint'],True)
            with patch.object(core,'open_request',side_effect=send):run.run(emit)
            self.assertEqual(events[-1]['status'],'completed',events)
            self.assertEqual(len([e for e in events if e['kind']=='operation_proposal']),1)
            visual=[b for b in bodies if 'data:image/png;base64,' in json.dumps(b)]
            self.assertEqual(len(visual),1);self.assertNotIn(base64.b64encode(png()).decode(),json.dumps(events))

    def test_image_continuation_across_provider_protocols(self):
        from test_code_agent import msg
        from test_routing import response,message,function_call
        from test_research import Response,answer,call as native_call
        for protocol,url in [('responses','https://gateway.example/v1'),('messages','https://gateway.example/v1'),('chat','http://localhost:11434/v1')]:
            with self.subTest(protocol=protocol,url=url),tempfile.TemporaryDirectory() as root:
                Path(root,'image.png').write_bytes(png());events=[];bodies=[]
                if protocol=='responses':
                    tool=dict(function_call('view'),name='view_image',arguments=json.dumps({'path':'image.png'}));replies=[Wire(response([tool]),False),Wire(response([message('red')]),False)]
                elif protocol=='messages':replies=[Wire(msg([{'type':'tool_use','id':'view','name':'view_image','input':{'path':'image.png'}}],'tool_use'),False),Wire(msg([{'type':'text','text':'red'}]),False)]
                else:replies=[Response([answer('',[native_call('view_image',{'path':'image.png'})])]),Response([answer('red')])]
                def send(c,endpoint,body,timeout):bodies.append(copy.deepcopy(body));return replies.pop(0)
                with patch.object(core,'open_request',side_effect=send):CodingRun(dict(C,url=url,protocol=protocol,stream=False),root,'Inspect',vision_enabled=True).run(events.append)
                self.assertEqual(events[-1]['status'],'completed',events)
                message_body=bodies[1]['input' if protocol=='responses' else 'messages'][-1]
                if protocol=='responses':self.assertEqual(message_body['content'][1]['type'],'input_image')
                elif protocol=='messages':self.assertEqual(message_body['content'][1]['type'],'image')
                else:self.assertEqual(message_body['images'],[base64.b64encode(png()).decode()])

    def test_vision_toggle_persists_in_code_session(self):
        import os
        os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
        from PySide6.QtWidgets import QApplication
        from agentnik.storage import Store
        from agentnik.ui import Window
        app=QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as root,patch.object(core,'discover',return_value={}),patch.object(core,'environment_connections',return_value={}):
            folder=Path(root,'project');folder.mkdir();store=Store(Path(root,'data'));window=Window(store)
            try:
                ident=window.repositories.put(folder);session=window.repositories.session(ident);store.save(session);window.open_session(session)
                tab=window.tabs.currentWidget();self.assertFalse(tab.vision_enabled.isChecked());tab.vision_enabled.setChecked(True)
                saved=next(item for item in store.list_sessions() if item['id']==session['id']);self.assertTrue(saved['coding_vision_enabled'])
                window.close_tab(window.tabs.indexOf(tab));window.open_session(saved);self.assertTrue(window.tabs.currentWidget().vision_enabled.isChecked())
            finally:window.close();app.processEvents();store.db.close()

    def test_changed_image_stops_subagent_batch_before_submission(self):
        with tempfile.TemporaryDirectory() as root:
            picture=Path(root,'slide.png');picture.write_bytes(png());events=[];bodies=[]
            tasks=[{'task':'Review slide','images':['slide.png']},{'task':'Review outline'}]
            run=CodingRun(dict(C,stream=False),root,'Review',vision_enabled=True)
            replies=[Wire(chat(calls=[call('delegate_subagents',{'tasks':json.dumps(tasks)})],finish='tool_calls'),False),Wire(chat('Stopped'),False)]
            def send(c,url,body,timeout):bodies.append(copy.deepcopy(body));return replies.pop(0)
            def emit(event):
                events.append(event)
                if event['kind']=='operation_proposal':
                    picture.write_bytes(b'changed');run.decide(event['fingerprint'],True)
            with patch.object(core,'open_request',side_effect=send):run.run(emit)
            self.assertEqual(len(bodies),2);self.assertFalse(any(e['kind']=='subagent' for e in events))
            self.assertIn('no tasks were started',json.dumps(bodies[1]))
