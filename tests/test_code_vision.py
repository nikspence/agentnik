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
