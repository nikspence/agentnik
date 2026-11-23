"""Offline Chat MCP integration: mocked model and disposable local server."""
import json
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch,Mock

os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from PySide6.QtWidgets import QApplication,QDialog
from agentnik import core,research
from agentnik.storage import Store
from agentnik.ui import Window
from test_routing import Wire,response,message

C={'url':'https://example.com/v1','protocol':'responses','model':'test','stream':False}


def function(name,arguments,ident):
    return {'type':'function_call','id':'fc-'+ident,'call_id':ident,'name':name,'arguments':json.dumps(arguments),'status':'completed'}


class ChatMCPIntegration(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.app=QApplication.instance() or QApplication([])

    def settle(self,predicate):
        end=time.monotonic()+10
        while not predicate() and time.monotonic()<end:self.app.processEvents();time.sleep(.005)
        self.assertTrue(predicate());self.app.processEvents()

    def test_server_guidance_reaches_chat_and_reconnect_defers_execution(self):
        import threading
        from agentnik.chat_mcp import MultiChatMCP
        servers=[{'name':name,'command':sys.executable,'args':[],'enabled':True} for name in ('First','Second')]
        group=MultiChatMCP(servers,{'mcp_servers':servers});tool={'name':'query','description':'Query','description_clipped':False,'schema_status':'available','schema':{'type':'object'}}
        for index,controller in enumerate(group.controllers):
            controller.bridge=Mock();controller.bridge.request.side_effect=[{'tool_details':[tool] if index==0 else [],'instructions':'Use precise account identifiers. model-secret-value' if index==0 else 'Read-only reference data.'},{'call_result':{'content':[{'type':'text','text':'done'}]}}]
        request={'request':json.dumps({'tool':'query','arguments':{}})}
        replies=[Wire(response([function('mcp_call',request,'one')]),False),Wire(response([function('mcp_call',request,'two')]),False),Wire(response([message('Done')]),False)];bodies=[]
        def send(c,url,body,timeout):bodies.append(json.loads(json.dumps(body)));return replies.pop(0)
        with patch.object(core,'open_request',side_effect=send):result=research.run_managed(dict(C,api_key='model-secret-value'),[{'role':'user','content':'Query'}],'',lambda _:None,threading.Event(),web_tools=False,mcp=group)
        self.assertEqual(result['status'],'ok');self.assertIn('Use precise account identifiers.',json.dumps(bodies[1]));self.assertIn('Read-only reference data.',json.dumps(bodies[1]));self.assertIn('No tools in this batch were executed',json.dumps(bodies[1]))
        self.assertEqual([item.args[0] for item in group.controllers[0].bridge.request.call_args_list],['discover','call'])
        self.assertNotIn('model-secret-value',json.dumps(result));self.assertNotIn('model-secret-value',json.dumps(bodies))
        self.assertEqual([item['status'] for item in result['research']['tool_records']],['skipped','completed'])

    def test_chat_explicit_discovery_returns_server_guidance(self):
        from agentnik.chat_mcp import ChatMCP
        from agentnik.tools import Runtime
        server={'name':'Example','command':sys.executable,'args':[],'enabled':True}
        controller=ChatMCP(server,{'mcp_servers':[server]});controller.bridge=Mock();controller.bridge.request.return_value={'tool_details':[],'instructions':'Use the account identifier.','instructions_clipped':True}
        result=controller.invoke('mcp_discover',{'server':'connect'},Runtime())
        self.assertEqual(result['instructions'],'Use the account identifier.');self.assertTrue(result['instructions_clipped']);self.assertIn('Untrusted',result['instructions_notice'])

    def test_automatic_mcp_precedence_displays_guidance_before_numeric_tool(self):
        import threading
        from agentnik.chat_mcp import ChatMCP
        server={'name':'Example','command':sys.executable,'args':[],'enabled':True}
        tool={'name':'calculate','description':'Calculate','description_clipped':False,'schema_status':'available','schema':{'type':'object','properties':{'expression':{'type':'string'}}}}
        controller=ChatMCP(server,{'mcp_servers':[server]});controller.bridge=Mock();controller.bridge.request.side_effect=[{'tool_details':[tool],'instructions':'This calculator uses approximate values.'},{'call_result':{'content':[{'type':'text','text':'4'}]}}]
        replies=[Wire(response([function('calculate',{'expression':'2+2'},'one')]),False),Wire(response([function('calculate',{'expression':'2+2'},'two')]),False),Wire(response([message('4')]),False)];bodies=[]
        def send(c,url,body,timeout):bodies.append(json.loads(json.dumps(body)));return replies.pop(0)
        with patch.object(core,'open_request',side_effect=send):result=research.run_managed(C,[{'role':'user','content':'Calculate'}],'',lambda _:None,threading.Event(),web_tools=False,local_tools=True,mcp=controller)
        self.assertEqual(result['status'],'ok');self.assertIn('approximate values',json.dumps(bodies[1]));self.assertEqual([entry.args[0] for entry in controller.bridge.request.call_args_list],['discover','call'])
        self.assertEqual([item['status'] for item in result['research']['tool_records']],['skipped','completed'])

    def test_chat_resources_require_listing_and_correct_server(self):
        from agentnik.chat_mcp import MultiChatMCP
        from agentnik.tools import Runtime,ResearchError
        servers=[{'name':name,'command':sys.executable,'args':[],'enabled':True} for name in ('First','Second')]
        group=MultiChatMCP(servers,{'mcp_servers':servers});runtime=Runtime()
        for controller in group.controllers:
            controller.bridge=Mock();controller.bridge.request.side_effect=[{'tool_details':[]},{'resources':[{'uri':'test://doc','name':controller.server['name']}],'more_resources':False},{'contents':[{'uri':'test://doc','text':'Evidence from '+controller.server['name']}]}]
        group.invoke('mcp_discover',{'server':'connect'},runtime)
        request={'request':json.dumps({'server':'Second','uri':'test://doc'})}
        with self.assertRaises(ResearchError):group.invoke('mcp_resources_read',request,runtime)
        listed=group.invoke('mcp_resources_list',{'server':'Second'},runtime);self.assertEqual(listed['resources'][0]['name'],'Second')
        result=group.invoke('mcp_resources_read',request,runtime);self.assertEqual(result['contents'][0]['text'],'Evidence from Second')
        with self.assertRaises(ResearchError):group.invoke('mcp_resources_read',{'request':json.dumps({'server':'First','uri':'test://doc'})},runtime)
        self.assertEqual(group.controllers[0].bridge.request.call_count,1)

    def test_chat_tool_links_stay_with_originating_server(self):
        from agentnik.chat_mcp import MultiChatMCP
        from agentnik.tools import Runtime,ResearchError
        servers=[{'name':name,'command':sys.executable,'args':[],'enabled':True} for name in ('First','Second')]
        group=MultiChatMCP(servers,{'mcp_servers':servers});runtime=Runtime()
        first,second=group.controllers;first.bridge=Mock();first.bridge.request.return_value={'tool_details':[]}
        tool={'name':'find','description':'Find','description_clipped':False,'schema_status':'available','schema':{'type':'object'}}
        second.bridge=Mock();second.bridge.request.side_effect=[{'tool_details':[tool]},{'call_result':{'content':[{'type':'resource_link','uri':'test://linked','name':'Link'}]}},{'contents':[{'uri':'test://linked','text':'Evidence'}]}]
        group.invoke('mcp_discover',{'server':'connect'},runtime);group.invoke('mcp_call',{'request':json.dumps({'server':'Second','tool':'find','arguments':{}})},runtime)
        with self.assertRaises(ResearchError):group.invoke('mcp_resources_read',{'request':json.dumps({'server':'First','uri':'test://linked'})},runtime)
        result=group.invoke('mcp_resources_read',{'request':json.dumps({'server':'Second','uri':'test://linked'})},runtime)
        self.assertEqual(result['contents'][0]['text'],'Evidence');self.assertEqual(first.bridge.request.call_count,1)

    def test_chat_prompts_are_server_scoped_and_keep_user_only_content_private(self):
        from agentnik.chat_mcp import MultiChatMCP
        from agentnik.tools import Runtime,ResearchError
        servers=[{'name':name,'command':sys.executable,'args':[],'enabled':True} for name in ('First','Second')]
        group=MultiChatMCP(servers,{'mcp_servers':servers});runtime=Runtime();events=[];runtime.notify=lambda *args:events.append(args)
        prompt={'name':'greet','description':'Greeting','arguments':[{'name':'name','description':'','required':True}]}
        for controller in group.controllers:
            controller.bridge=Mock();controller.bridge.request.side_effect=[{'tool_details':[]},{'prompts':[prompt]},{'messages':[{'role':'user','content':{'type':'text','text':'Hello world'}},{'role':'assistant','content':{'type':'image','mimeType':'image/png','data':'large-image'}}],'user_text':['Private for user'],'user_nontext':0}]
        group.invoke('mcp_discover',{'server':'connect'},runtime)
        request={'request':json.dumps({'server':'Second','name':'greet','arguments':{'name':'world'}})}
        with self.assertRaises(ResearchError):group.invoke('mcp_prompts_get',request,runtime)
        group.invoke('mcp_prompts_list',{'server':'Second'},runtime)
        for bad in ({'server':'First','name':'greet','arguments':{'name':'world'}},{'server':'Second','name':'greet','arguments':{}},{'server':'Second','name':'greet','arguments':{'name':42}}):
            with self.assertRaises(ResearchError):group.invoke('mcp_prompts_get',{'request':json.dumps(bad)},runtime)
        result=group.invoke('mcp_prompts_get',request,runtime);encoded=json.dumps(result)
        self.assertIn('Hello world',encoded);self.assertNotIn('Private for user',encoded);self.assertNotIn('large-image',encoded);self.assertIn('Private for user',str(events));self.assertEqual(group.controllers[0].bridge.request.call_count,1)

    def test_chat_prompt_listing_reconnects_without_reusing_old_listing(self):
        from agentnik.chat_mcp import ChatMCP,MultiChatMCP
        from agentnik.tools import ResearchError
        servers=[{'name':name,'command':sys.executable,'args':[],'enabled':True} for name in ('First','Second')]
        single=ChatMCP(servers[0],{'mcp_servers':servers});multi=MultiChatMCP(servers,{'mcp_servers':servers})
        self.assertTrue(single.needs_reconnect([('mcp_prompts_list',{'server':'First'})]));self.assertTrue(multi.needs_reconnect([('mcp_prompts_list',{'server':'Second'})]))
        self.assertTrue(single.needs_reconnect([('mcp_templates_list',{'server':'First'})]));self.assertTrue(multi.needs_reconnect([('mcp_templates_list',{'server':'Second'})]))
        request={'request':json.dumps({'server':'First','name':'old','arguments':{}})}
        with self.assertRaises(ResearchError):single.validate_call('mcp_prompts_get',request)

    def test_chat_templates_are_scoped_and_expand_validated_variables(self):
        from agentnik.chat_mcp import MultiChatMCP
        from agentnik.tools import Runtime,ResearchError
        servers=[{'name':name,'command':sys.executable,'args':[],'enabled':True} for name in ('First','Second')]
        group=MultiChatMCP(servers,{'mcp_servers':servers});runtime=Runtime()
        template={'uriTemplate':'test://item{/id}{?q*}','name':'Item','description':'','mimeType':'','supported':True,'variables':['id','q']}
        for controller in group.controllers:
            controller.bridge=Mock();controller.bridge.request.side_effect=[{'tool_details':[]},{'templates':[template]},{'contents':[{'uri':'test://item/a%2Fb?q=x&q=y','text':'Found item'}]}]
        group.invoke('mcp_discover',{'server':'connect'},runtime)
        request={'request':json.dumps({'server':'Second','template':template['uriTemplate'],'variables':{'id':'a/b','q':['x','y']}})}
        with self.assertRaises(ResearchError):group.invoke('mcp_templates_read',request,runtime)
        group.invoke('mcp_templates_list',{'server':'Second'},runtime)
        result=group.invoke('mcp_templates_read',request,runtime);self.assertEqual(result['contents'][0]['text'],'Found item')
        payload=group.controllers[1].bridge.request.call_args.args[1];self.assertEqual(payload['uri'],'test://item/a%2Fb?q=x&q=y')
        for bad in ({'server':'First','template':template['uriTemplate'],'variables':{'id':'x'}},{'server':'Second','template':'unlisted','variables':{}},{'server':'Second','template':template['uriTemplate'],'variables':{'id':123}}):
            with self.assertRaises(ResearchError):group.invoke('mcp_templates_read',{'request':json.dumps(bad)},runtime)
        group.controllers[1].secret_values=['sensitive']
        with self.assertRaises(ResearchError):group.invoke('mcp_templates_read',{'request':json.dumps({'server':'Second','template':template['uriTemplate'],'variables':{'id':'sensitive'}})},runtime)
        self.assertEqual(group.controllers[0].bridge.request.call_count,1)

    def test_chat_reads_template_from_real_local_mcp_server(self):
        with tempfile.TemporaryDirectory() as folder,patch.object(core,'discover',return_value={}),patch.object(core,'environment_connections',return_value={}),patch.object(core,'models',return_value=[]):
            root=Path(folder);server=root/'server.py'
            server.write_text('''import json,sys
for line in sys.stdin:
 req=json.loads(line);method=req['method']
 if method=='server/discover':print(json.dumps({'jsonrpc':'2.0','id':req['id'],'error':{'code':-32601,'message':'unsupported'}}),flush=True);continue
 if method=='notifications/initialized':continue
 if method=='initialize':result={'protocolVersion':req['params']['protocolVersion'],'serverInfo':{'name':'Fake','version':'1'},'capabilities':{'resources':{}}}
 elif method=='resources/templates/list':result={'resourceTemplates':[{'uriTemplate':'test://item{/id}{?q*}','name':'Item'}]}
 elif method=='resources/read':result={'contents':[{'uri':req['params']['uri'],'text':'Synthetic '+req['params']['uri']}]}
 else:raise RuntimeError('unexpected '+method)
 print(json.dumps({'jsonrpc':'2.0','id':req['id'],'result':result}),flush=True)
''',encoding='utf-8')
            store=Store(root/'data');store.config['mcp_servers']=[{'name':'Documents','command':sys.executable,'args':[str(server)],'enabled':True}];store.flush();window=Window(store);window.connections={'test':dict(C)}
            request=json.dumps({'server':'Documents','template':'test://item{/id}{?q*}','variables':{'id':'a/b','q':['one','two']}});bodies=[]
            replies=[Wire(response([function('mcp_discover',{'server':'connect'},'one')]),False),Wire(response([function('mcp_templates_list',{'server':'Documents'},'two')]),False),Wire(response([function('mcp_templates_read',{'request':request},'three')]),False),Wire(response([message('Read')]),False)]
            def send(c,url,body,timeout):bodies.append(json.dumps(body));return replies.pop(0)
            try:
                window.new_session('chat','test');tab=window.tabs.currentWidget();tab.mcp_choice.setCurrentIndex(1);tab.composer.setPlainText('Read item')
                with patch.object(core,'open_request',side_effect=send):tab.submit();self.settle(lambda:tab.job is None)
                self.assertEqual(tab.session['messages'][-1]['text'],'Read');self.assertIn('Synthetic test://item/a%2Fb?q=one&q=two',bodies[-1])
            finally:window.close();self.app.processEvents();store.db.close()

    def test_chat_retrieves_real_local_mcp_server_prompt(self):
        with tempfile.TemporaryDirectory() as folder,patch.object(core,'discover',return_value={}),patch.object(core,'environment_connections',return_value={}),patch.object(core,'models',return_value=[]):
            root=Path(folder);server=root/'server.py'
            server.write_text('''import json,sys
for line in sys.stdin:
 req=json.loads(line);method=req['method']
 if method=='server/discover':print(json.dumps({'jsonrpc':'2.0','id':req['id'],'error':{'code':-32601,'message':'unsupported'}}),flush=True);continue
 if method=='notifications/initialized':continue
 if method=='initialize':result={'protocolVersion':req['params']['protocolVersion'],'serverInfo':{'name':'Fake','version':'1'},'capabilities':{'prompts':{}}}
 elif method=='prompts/list':result={'prompts':[{'name':'greet','arguments':[{'name':'name','required':True}]}]}
 elif method=='prompts/get':result={'messages':[{'role':'user','content':{'type':'text','text':'Hello '+req['params']['arguments']['name']}},{'role':'user','content':{'type':'text','text':'private-user-text','annotations':{'audience':['user']}}}]}
 else:raise RuntimeError('unexpected '+method)
 print(json.dumps({'jsonrpc':'2.0','id':req['id'],'result':result}),flush=True)
''',encoding='utf-8')
            store=Store(root/'data');store.config['mcp_servers']=[{'name':'Prompts','command':sys.executable,'args':[str(server)],'enabled':True}];store.flush();window=Window(store);window.connections={'test':dict(C)}
            request=json.dumps({'server':'Prompts','name':'greet','arguments':{'name':'world'}});bodies=[]
            replies=[Wire(response([function('mcp_discover',{'server':'connect'},'one')]),False),Wire(response([function('mcp_prompts_list',{'server':'Prompts'},'two')]),False),Wire(response([function('mcp_prompts_get',{'request':request},'three')]),False),Wire(response([message('Hello world')]),False)]
            def send(c,url,body,timeout):bodies.append(json.dumps(body));return replies.pop(0)
            try:
                window.new_session('chat','test');tab=window.tabs.currentWidget();tab.mcp_choice.setCurrentIndex(1);tab.composer.setPlainText('Get greeting')
                with patch.object(core,'open_request',side_effect=send):tab.submit();self.settle(lambda:tab.job is None)
                self.assertEqual(tab.session['messages'][-1]['text'],'Hello world');self.assertIn('Hello world',bodies[-1]);self.assertNotIn('private-user-text',bodies[-1]);self.assertIn('private-user-text',str(tab.session['messages'][-1]['research']['events']))
            finally:window.close();self.app.processEvents();store.db.close()

    def test_chat_model_reads_mcp_resource_over_existing_loop(self):
        import threading
        from agentnik.chat_mcp import ChatMCP
        server={'name':'Documents','command':sys.executable,'args':[],'enabled':True}
        controller=ChatMCP(server,{'mcp_servers':[server]});controller.bridge=Mock()
        controller.bridge.request.side_effect=[{'tool_details':[]},{'resources':[{'uri':'test://report','name':'report'}],'more_resources':False},{'contents':[{'uri':'test://report','text':'Revenue was 42.'}]}]
        request=json.dumps({'server':'Documents','uri':'test://report'})
        replies=[Wire(response([function('mcp_discover',{'server':'connect'},'one')]),False),Wire(response([function('mcp_resources_list',{'server':'Documents'},'two')]),False),Wire(response([function('mcp_resources_read',{'request':request},'three')]),False),Wire(response([message('Revenue was 42.')]),False)]
        bodies=[]
        def send(c,url,body,timeout):bodies.append(json.loads(json.dumps(body)));return replies.pop(0)
        with patch.object(core,'open_request',side_effect=send):result=research.run_managed(C,[{'role':'user','content':'Read report'}],'',lambda _:None,threading.Event(),web_tools=False,mcp=controller)
        self.assertEqual(result['status'],'ok');self.assertIn('Revenue was 42.',json.dumps(bodies[-1]));self.assertEqual([item.args[0] for item in controller.bridge.request.call_args_list],['discover','resources_list','resources_read'])

    def test_chat_model_receives_large_prompt_without_user_only_content(self):
        import threading
        from agentnik.chat_mcp import ChatMCP
        from agentnik.mcp_prompts import parse_prompt_messages
        server={'name':'Prompts','command':sys.executable,'args':[],'enabled':True};public='Public 雪 '*5000;private='Private-only '*4000
        prompt={'name':'review','description':'Review','arguments':[]};contents=parse_prompt_messages({'messages':[{'role':'user','content':{'type':'text','text':public}},{'role':'assistant','content':{'type':'text','text':private,'annotations':{'audience':['user']}}}]})
        controller=ChatMCP(server,{'mcp_servers':[server]});controller.bridge=Mock();controller.bridge.request.side_effect=[{'tool_details':[]},{'prompts':[prompt]},contents]
        request=json.dumps({'server':'Prompts','name':'review','arguments':{}})
        replies=[Wire(response([function('mcp_discover',{'server':'connect'},'one')]),False),Wire(response([function('mcp_prompts_list',{'server':'Prompts'},'two')]),False),Wire(response([function('mcp_prompts_get',{'request':request},'three')]),False),Wire(response([message('Read')]),False)];bodies=[]
        def send(c,url,body,timeout):bodies.append(json.loads(json.dumps(body)));return replies.pop(0)
        with patch.object(core,'open_request',side_effect=send):result=research.run_managed(C,[{'role':'user','content':'Read'}],'',lambda _:None,threading.Event(),web_tools=False,mcp=controller)
        self.assertEqual(result['status'],'ok');self.assertIn(public,json.dumps(bodies[-1],ensure_ascii=False));self.assertNotIn('Private-only',json.dumps(bodies[-1]))

    def test_chat_model_receives_large_mcp_text_resource(self):
        import threading
        from agentnik.chat_mcp import ChatMCP
        from agentnik.mcp_resources import parse_resource_contents
        server={'name':'Documents','command':sys.executable,'args':[],'enabled':True};uri='test://report';text='Account 雪: 42 '*5000
        contents=parse_resource_contents({'contents':[{'uri':uri,'text':text}]},uri)['contents']
        controller=ChatMCP(server,{'mcp_servers':[server]});controller.bridge=Mock();controller.bridge.request.side_effect=[{'tool_details':[]},{'resources':[{'uri':uri,'name':'report'}]},{'contents':contents}]
        request=json.dumps({'server':'Documents','uri':uri})
        replies=[Wire(response([function('mcp_discover',{'server':'connect'},'one')]),False),Wire(response([function('mcp_resources_list',{'server':'Documents'},'two')]),False),Wire(response([function('mcp_resources_read',{'request':request},'three')]),False),Wire(response([message('Read')]),False)];bodies=[]
        def send(c,url,body,timeout):bodies.append(json.loads(json.dumps(body)));return replies.pop(0)
        with patch.object(core,'open_request',side_effect=send):result=research.run_managed(C,[{'role':'user','content':'Read'}],'',lambda _:None,threading.Event(),web_tools=False,mcp=controller)
        self.assertEqual(result['status'],'ok');self.assertIn(text,json.dumps(bodies[-1],ensure_ascii=False))

    def test_chat_continues_after_oversized_mcp_result_without_repeating_call(self):
        import base64,threading
        from agentnik.chat_mcp import ChatMCP
        from agentnik.tools import Limits
        from test_image_generation import png
        server={'name':'Example','command':sys.executable,'args':[],'enabled':True};tool={'name':'query','description':'Query','description_clipped':False,'schema_status':'available','schema':{'type':'object'}}
        encoded=base64.b64encode(png()).decode('ascii');controller=ChatMCP(server,{'mcp_servers':[server]},vision_enabled=True);controller.tools=[tool];controller.bridge=Mock()
        controller.bridge.request.return_value={'call_result':{'content':[{'type':'text','text':'Evidence 雪 '*10000+' model-secret-value'},{'type':'image','mimeType':'image/png','data':encoded}]}}
        request=json.dumps({'tool':'query','arguments':{}});replies=[Wire(response([function('mcp_call',{'request':request},'one')]),False),Wire(response([message('Partial result')]),False)];bodies=[]
        def send(c,url,body,timeout):bodies.append(json.loads(json.dumps(body)));return replies.pop(0)
        with patch.object(core,'open_request',side_effect=send):result=research.run_managed(dict(C,api_key='model-secret-value'),[{'role':'user','content':'Query'}],'',lambda _:None,threading.Event(),limits=Limits(context_bytes=6000),web_tools=False,mcp=controller)
        self.assertEqual(result['status'],'ok');self.assertEqual(controller.bridge.request.call_count,1)
        body=json.dumps(bodies[-1],ensure_ascii=False);self.assertIn('partial, untrusted JSON preview',body);self.assertIn('No retry was made',body);self.assertNotIn(encoded,body);self.assertNotIn('model-secret-value',body)
        self.assertTrue(any('partial preview' in item['detail'] for item in result['research']['events']));self.assertEqual(controller.take_images(),[])

    def test_partial_mcp_result_preserves_images_from_earlier_batch_calls(self):
        import base64,threading
        from agentnik.chat_mcp import ChatMCP
        from agentnik.tools import Limits
        from test_image_generation import png
        server={'name':'Example','command':sys.executable,'args':[],'enabled':True};tool={'name':'query','description':'Query','description_clipped':False,'schema_status':'available','schema':{'type':'object'}}
        image={'type':'image','mimeType':'image/png','data':base64.b64encode(png()).decode('ascii')}
        controller=ChatMCP(server,{'mcp_servers':[server]},vision_enabled=True);controller.tools=[tool];controller.bridge=Mock();controller.bridge.request.side_effect=[{'call_result':{'content':[image]}},{'call_result':{'content':[{'type':'text','text':'x'*30000},image]}}]
        request=json.dumps({'tool':'query','arguments':{}});replies=[Wire(response([function('mcp_call',{'request':request},'one'),function('mcp_call',{'request':request},'two')]),False),Wire(response([message('Partial result')]),False)];bodies=[]
        def send(c,url,body,timeout):bodies.append(json.loads(json.dumps(body)));return replies.pop(0)
        with patch.object(core,'open_request',side_effect=send):result=research.run_managed(C,[{'role':'user','content':'Query'}],'',lambda _:None,threading.Event(),limits=Limits(context_bytes=6000),web_tools=False,mcp=controller)
        self.assertEqual(result['status'],'ok');visual=bodies[-1]['input'][-1]['content'];self.assertEqual(sum(item.get('type')=='input_image' for item in visual),1)
        self.assertIn('MCP image 1',visual[0]['text']);self.assertNotIn('MCP image 2',visual[0]['text']);self.assertEqual(controller.bridge.request.call_count,2)

    def test_chat_mcp_images_are_opt_in_bounded_and_transient(self):
        import base64,threading
        from agentnik.chat_mcp import ChatMCP
        from test_image_generation import png
        image=base64.b64encode(png()).decode('ascii')
        server={'name':'Documents','command':sys.executable,'args':[],'enabled':True}
        tool={'name':'picture','description':'Picture','description_clipped':False,'schema_status':'available','schema':{'type':'object'}}
        request=json.dumps({'tool':'picture','arguments':{}})
        for enabled in (False,True):
            with self.subTest(enabled=enabled):
                controller=ChatMCP(server,{'mcp_servers':[server]},vision_enabled=enabled);controller.bridge=Mock()
                block={'type':'image','mimeType':'image/png','data':image}
                private=dict(block,annotations={'audience':['user']})
                controller.bridge.request.side_effect=[{'tool_details':[tool]},{'call_result':{'content':[block]*5+[private]}}]
                replies=[Wire(response([function('mcp_discover',{'server':'connect'},'one')]),False),Wire(response([function('mcp_call',{'request':request},'two')]),False),Wire(response([message('Done')]),False)]
                bodies=[]
                def send(c,url,body,timeout):bodies.append(json.loads(json.dumps(body)));return replies.pop(0)
                with patch.object(core,'open_request',side_effect=send):result=research.run_managed(C,[{'role':'user','content':'Inspect'}],'',lambda _:None,threading.Event(),web_tools=False,mcp=controller)
                self.assertEqual(result['status'],'ok');self.assertNotIn(image,json.dumps(result))
                content=bodies[-1]['input'];visual=[item for item in content if item.get('role')=='user' and isinstance(item.get('content'),list) and any(part.get('type')=='input_image' for part in item['content'])]
                self.assertEqual(len(visual),int(enabled))
                if enabled:
                    self.assertEqual(sum(part.get('type')=='input_image' for part in visual[0]['content']),4)
                    self.assertIn('batch limit',json.dumps(content));self.assertEqual(controller.take_images(),[])
                else:self.assertNotIn(image,json.dumps(content))

    def test_chat_mcp_image_option_is_saved_per_chat(self):
        with tempfile.TemporaryDirectory() as folder,patch.object(core,'discover',return_value={}),patch.object(core,'environment_connections',return_value={}),patch.object(core,'models',return_value=[]):
            store=Store(folder);window=Window(store);window.connections={'test':dict(C)}
            try:
                window.new_session('chat','test');tab=window.tabs.currentWidget()
                self.assertFalse(tab.mcp_vision.isChecked());tab.mcp_vision.setChecked(True)
                saved=next(item for item in store.list_sessions() if item['id']==tab.session['id'])
                self.assertTrue(saved['research_options']['mcp_vision_enabled'])
                tab.busy(True);self.assertFalse(tab.mcp_vision.isEnabled());tab.busy(False)
            finally:window.close();self.app.processEvents();store.db.close()

    def test_mcp_image_budget_keeps_fitting_images_and_explains_omissions(self):
        import base64,threading
        from agentnik.chat_mcp import ChatMCP
        from agentnik.tools import Limits
        from test_image_generation import png
        server={'name':'Pictures','command':sys.executable,'args':[],'enabled':True}
        tool={'name':'picture','description':'Picture','description_clipped':False,'schema_status':'available','schema':{'type':'object'}}
        small=png();large=small+b'x'*12000
        blocks=[{'type':'image','mimeType':'image/png','data':base64.b64encode(data).decode('ascii')} for data in (large,small)]
        controller=ChatMCP(server,{'mcp_servers':[server]},vision_enabled=True);controller.bridge=Mock();controller.tools=[tool]
        controller.bridge.request.return_value={'call_result':{'content':blocks}}
        request=json.dumps({'tool':'picture','arguments':{}})
        replies=[Wire(response([function('mcp_call',{'request':request},'one')]),False),Wire(response([message('Done')]),False)];bodies=[]
        def send(c,url,body,timeout):bodies.append(json.loads(json.dumps(body)));return replies.pop(0)
        with patch.object(core,'open_request',side_effect=send):
            result=research.run_managed(C,[{'role':'user','content':'Inspect'}],'',lambda _:None,threading.Event(),limits=Limits(context_bytes=6000),web_tools=False,mcp=controller)
        self.assertEqual(result['status'],'ok');last=json.dumps(bodies[-1]);self.assertIn(base64.b64encode(small).decode('ascii'),last)
        self.assertNotIn(base64.b64encode(large).decode('ascii'),last);self.assertIn('omitted because the research context limit',last)
        visual=bodies[-1]['input'][-1]['content'][0]['text']
        self.assertIn('MCP image 2',visual);self.assertIn('Omitted image labels: ["MCP image 1"]',visual)
        self.assertIn('1 omitted due to the research context limit',json.dumps(result['research']['events']))
        self.assertNotIn(base64.b64encode(small).decode('ascii'),json.dumps(result))

    def test_mcp_image_budget_reports_all_omissions_for_each_protocol(self):
        from test_image_generation import png
        images=[('large',png()+b'x'*5000,'image/png')]
        for protocol,native in (('responses',False),('chat',False),('messages',False),('chat',True)):
            with self.subTest(protocol=protocol,native=native):
                visual,included,size=research.mcp_image_message(images,protocol,native,1000)
                self.assertEqual(included,0);self.assertLessEqual(size,1000)
                self.assertIn('1 MCP image(s) were omitted',json.dumps(visual));self.assertNotIn('images',visual)

    def test_chat_mcp_image_batch_limit_is_shared_between_servers(self):
        import base64
        from agentnik.chat_mcp import MultiChatMCP
        from agentnik.tools import Runtime
        from test_image_generation import png
        servers=[{'name':name,'command':sys.executable,'args':[],'enabled':True} for name in ('First','Second')]
        group=MultiChatMCP(servers,{'mcp_servers':servers},vision_enabled=True)
        tool={'name':'picture','description':'Picture','description_clipped':False,'schema_status':'available','schema':{'type':'object'}}
        image=base64.b64encode(png()).decode('ascii');block={'type':'image','mimeType':'image/png','data':image}
        for controller in group.controllers:
            controller.tools=[tool];controller.bridge=Mock();controller.bridge.request.return_value={'call_result':{'content':[block]*3}}
        outputs=[]
        for controller in group.controllers:
            outputs.append(controller.invoke('mcp_call',{'request':json.dumps({'tool':'picture','arguments':{}})},Runtime()))
        first=group.take_images();self.assertEqual([item[0] for item in first],['MCP image 1','MCP image 2','MCP image 3','MCP image 4'])
        self.assertIn('MCP image 3',json.dumps(outputs[0]));self.assertIn('MCP image 4',json.dumps(outputs[1]));self.assertEqual(group.take_images(),[])
        group.controllers[0].invoke('mcp_call',{'request':json.dumps({'tool':'picture','arguments':{}})},Runtime())
        self.assertEqual(group.take_images()[0][0],'MCP image 5')

    def test_chat_resource_list_reconnects_and_read_requires_fresh_listing(self):
        import threading
        from agentnik.chat_mcp import ChatMCP
        server={'name':'Documents','command':sys.executable,'args':[],'enabled':True}
        controller=ChatMCP(server,{'mcp_servers':[server]});controller.bridge=Mock();controller.bridge.request.side_effect=[{'tool_details':[]},{'resources':[{'uri':'test://report','name':'Report'}]}]
        request=json.dumps({'server':'Documents','uri':'test://report'});bodies=[]
        replies=[Wire(response([function('mcp_resources_read',{'request':request},'one')]),False),Wire(response([function('mcp_resources_list',{'server':'Documents'},'two')]),False),Wire(response([message('Listed')]),False)]
        def send(c,url,body,timeout):bodies.append(json.dumps(body));return replies.pop(0)
        with patch.object(core,'open_request',side_effect=send):result=research.run_managed(C,[{'role':'user','content':'List report'}],'',lambda _:None,threading.Event(),web_tools=False,mcp=controller)
        self.assertEqual(result['status'],'ok');self.assertIn('List MCP resources or obtain a resource link',bodies[1]);self.assertEqual([item.args[0] for item in controller.bridge.request.call_args_list],['discover','resources_list'])

    def test_chat_reads_tool_resource_link_without_listing(self):
        with tempfile.TemporaryDirectory() as folder,patch.object(core,'discover',return_value={}),patch.object(core,'environment_connections',return_value={}),patch.object(core,'models',return_value=[]):
            root=Path(folder);server=root/'server.py'
            server.write_text('''import json,sys
for line in sys.stdin:
 req=json.loads(line);method=req['method']
 if method=='server/discover':print(json.dumps({'jsonrpc':'2.0','id':req['id'],'error':{'code':-32601,'message':'unsupported'}}),flush=True);continue
 if method=='notifications/initialized':continue
 if method=='initialize':result={'protocolVersion':req['params']['protocolVersion'],'serverInfo':{'name':'Fake','version':'1'},'capabilities':{'tools':{},'resources':{}}}
 elif method=='tools/list':result={'tools':[{'name':'find','inputSchema':{'type':'object'}}]}
 elif method=='tools/call':result={'content':[{'type':'resource_link','uri':'test://public','name':'Public'},{'type':'resource_link','uri':'test://private','name':'Private','annotations':{'audience':['user']}}]}
 elif method=='resources/read':result={'contents':[{'uri':req['params']['uri'],'text':'Linked evidence'}]}
 else:raise RuntimeError('unexpected '+method)
 print(json.dumps({'jsonrpc':'2.0','id':req['id'],'result':result}),flush=True)
''',encoding='utf-8')
            store=Store(root/'data');store.config['mcp_servers']=[{'name':'Documents','command':sys.executable,'args':[str(server)],'enabled':True}];store.flush();window=Window(store);window.connections={'test':dict(C)}
            call=json.dumps({'tool':'find','arguments':{}});private=json.dumps({'server':'Documents','uri':'test://private'});public=json.dumps({'server':'Documents','uri':'test://public'});bodies=[]
            replies=[Wire(response([function('mcp_discover',{'server':'connect'},'one')]),False),Wire(response([function('mcp_call',{'request':call},'two')]),False),Wire(response([function('mcp_resources_read',{'request':private},'three')]),False),Wire(response([function('mcp_resources_read',{'request':public},'four')]),False),Wire(response([message('Found evidence')]),False)]
            def send(c,url,body,timeout):bodies.append(json.dumps(body));return replies.pop(0)
            try:
                window.new_session('chat','test');tab=window.tabs.currentWidget();tab.mcp_choice.setCurrentIndex(1);tab.composer.setPlainText('Find evidence')
                with patch.object(core,'open_request',side_effect=send):tab.submit();self.settle(lambda:tab.job is None)
                self.assertEqual(tab.session['messages'][-1]['text'],'Found evidence');self.assertIn('resource_links_available',bodies[2]);self.assertIn('Choose a listed resource',bodies[3]);self.assertIn('Linked evidence',bodies[-1])
            finally:window.close();self.app.processEvents();store.db.close()

    def test_chat_reads_real_local_mcp_server_resource(self):
        with tempfile.TemporaryDirectory() as folder,patch.object(core,'discover',return_value={}),patch.object(core,'environment_connections',return_value={}),patch.object(core,'models',return_value=[]):
            root=Path(folder);server=root/'server.py'
            server.write_text('''import json,sys
for line in sys.stdin:
 req=json.loads(line);method=req['method']
 if method=='server/discover':print(json.dumps({'jsonrpc':'2.0','id':req['id'],'error':{'code':-32601,'message':'unsupported'}}),flush=True);continue
 if method=='notifications/initialized':continue
 if method=='initialize':result={'protocolVersion':req['params']['protocolVersion'],'serverInfo':{'name':'Fake','version':'1'},'capabilities':{'resources':{}}}
 elif method=='resources/list':result={'resources':[{'uri':'test://report','name':'Report'}]}
 elif method=='resources/read':result={'contents':[{'uri':req['params']['uri'],'text':'Synthetic evidence 42'}]}
 else:raise RuntimeError('unexpected '+method)
 print(json.dumps({'jsonrpc':'2.0','id':req['id'],'result':result}),flush=True)
''',encoding='utf-8')
            store=Store(root/'data');store.config['mcp_servers']=[{'name':'Documents','command':sys.executable,'args':[str(server)],'enabled':True}];store.flush();window=Window(store);window.connections={'test':dict(C)}
            request=json.dumps({'server':'Documents','uri':'test://report'});bodies=[]
            replies=[Wire(response([function('mcp_discover',{'server':'connect'},'one')]),False),Wire(response([function('mcp_resources_list',{'server':'Documents'},'two')]),False),Wire(response([function('mcp_resources_read',{'request':request},'three')]),False),Wire(response([message('Evidence 42')]),False)]
            def send(c,url,body,timeout):bodies.append(json.dumps(body));return replies.pop(0)
            try:
                window.new_session('chat','test');tab=window.tabs.currentWidget();tab.mcp_choice.setCurrentIndex(1);tab.composer.setPlainText('Read report')
                with patch.object(core,'open_request',side_effect=send):tab.submit();self.settle(lambda:tab.job is None)
                self.assertEqual(tab.session['messages'][-1]['text'],'Evidence 42');self.assertIn('Synthetic evidence 42',bodies[-1]);self.assertEqual(tab.session['messages'][-1]['research']['status'],'completed')
            finally:window.close();self.app.processEvents();store.db.close()

    def test_chat_replaces_mcp_binary_media_with_notices(self):
        from agentnik.chat_mcp import ChatMCP
        from agentnik.tools import Runtime
        server={'name':'Test','command':sys.executable,'args':[],'enabled':True}
        tool={'name':'media','description':'Media','description_clipped':False,'schema_status':'available','schema':{'type':'object'}}
        controller=ChatMCP(server,{'mcp_servers':[server]});controller.bridge=Mock()
        controller.bridge.request.side_effect=[{'tool_details':[tool]},{'call_result':{'content':[{'type':'text','text':'description'},{'type':'image','mimeType':'image/png','data':'image-secret-payload'},{'type':'audio','mimeType':'audio/wav','data':'audio-secret-payload'},{'type':'resource','resource':{'uri':'test://image','mimeType':'image/png','blob':'resource-secret-payload'}}]}}]
        runtime=Runtime();controller.invoke('mcp_discover',{'server':'connect'},runtime)
        result=controller.invoke('mcp_call',{'request':json.dumps({'tool':'media','arguments':{}})},runtime)
        serialized=json.dumps(result)
        self.assertIn('description',serialized);self.assertIn('Image inspection is disabled or unavailable',serialized);self.assertIn('audio content is not supported',serialized)
        self.assertNotIn('secret-payload',serialized)

    def test_chat_reports_schema_field_without_echoing_argument_values(self):
        from agentnik.chat_mcp import ChatMCP
        from agentnik.tools import Runtime,ResearchError
        server={'name':'Test','command':sys.executable,'args':[],'enabled':True}
        controller=ChatMCP(server,{'mcp_servers':[server]});controller.bridge=Mock()
        controller.tools=[{'name':'query','description':'Query','description_clipped':False,'schema_status':'available','schema':{'type':'object','properties':{'count':{'type':'integer'}},'required':['count']}}]
        args={'request':json.dumps({'tool':'query','arguments':{'count':'private-value'}})}
        with self.assertRaises(ResearchError) as error:controller.invoke('mcp_call',args,Runtime())
        self.assertIn('count',str(error.exception));self.assertIn('wrong type',str(error.exception));self.assertNotIn('private-value',str(error.exception));controller.bridge.request.assert_not_called()

    def test_cancelled_chat_records_confirmed_task_cleanup_in_original_run(self):
        with tempfile.TemporaryDirectory() as folder,patch.object(core,'discover',return_value={}),patch.object(core,'environment_connections',return_value={}),patch.object(core,'models',return_value=[]):
            root=Path(folder);server=root/'server.py'
            server.write_text('''import json,sys
for line in sys.stdin:
 req=json.loads(line);method=req['method']
 if method=='server/discover':print(json.dumps({'jsonrpc':'2.0','id':req['id'],'error':{'code':-32601,'message':'unsupported'}}),flush=True);continue
 if method=='notifications/initialized':continue
 if method=='initialize':result={'protocolVersion':req['params']['protocolVersion'],'serverInfo':{'name':'Fake','version':'1'},'capabilities':{'tools':{},'tasks':{'cancel':{},'requests':{'tools':{'call':{}}}}}}
 elif method=='tools/list':result={'tools':[{'name':'work','inputSchema':{'type':'object'},'execution':{'taskSupport':'required'}}]}
 elif method=='tools/call':result={'task':{'taskId':'task-123','status':'working','createdAt':'2026-01-01T00:00:00Z','lastUpdatedAt':'2026-01-01T00:00:00Z','ttl':60000}}
 elif method=='tasks/result':continue
 elif method=='tasks/cancel':result={'taskId':'task-123','status':'cancelled'}
 else:raise RuntimeError('unexpected '+method)
 print(json.dumps({'jsonrpc':'2.0','id':req['id'],'result':result}),flush=True)
''',encoding='utf-8')
            store=Store(root/'data');store.config['mcp_servers']=[{'name':'Local','command':sys.executable,'args':[str(server)],'enabled':True}];store.flush();window=Window(store);window.connections={'test':dict(C)}
            request=json.dumps({'tool':'work','arguments':{}});replies=[Wire(response([function('mcp_discover',{'server':'connect'},'first')]),False),Wire(response([function('mcp_call',{'request':request},'second')]),False)]
            try:
                window.new_session('chat','test');tab=window.tabs.currentWidget();tab.mcp_choice.setCurrentIndex(1);tab.composer.setPlainText('Run task')
                with patch.object(core,'open_request',side_effect=replies):
                    tab.submit();self.settle(lambda:tab.partial and 'Task started: task-123' in str(tab.partial.get('research',{}).get('events',[])));tab.cancel()
                    self.settle(lambda:bool(tab.session['messages']) and 'cancellation confirmed' in str(tab.session['messages'][-1].get('research',{}).get('events',[])))
                events=tab.session['messages'][-1]['research']['events'];self.assertEqual(sum('cancellation confirmed' in event.get('detail','') for event in events),1)
                saved=next(item for item in store.list_sessions() if item['id']==tab.session['id']);self.assertIn('task-123',str(saved['messages'][-1]['research']['events']))
            finally:window.close();self.app.processEvents();store.db.close()

    def test_task_cleanup_updates_matching_chat_run_and_redacts_secrets(self):
        with tempfile.TemporaryDirectory() as folder,patch.object(core,'discover',return_value={}),patch.object(core,'environment_connections',return_value={}):
            store=Store(folder);window=Window(store);window.connections={'test':dict(C)}
            try:
                window.new_session('chat','test');tab=window.tabs.currentWidget()
                tab.session['messages']=[{'role':'assistant','text':'First','research':{'run_id':'first','events':[]}},{'role':'assistant','text':'Second','research':{'run_id':'second','events':[]}}]
                tab.record_mcp_task_cleanup({'server':'Local','task_id':'task-secret-value','task_cancelled':False},'first',('secret-value',))
                first,second=tab.session['messages'];self.assertIn('not confirmed',first['research']['events'][0]['detail']);self.assertIn('[redacted]',first['research']['events'][0]['detail']);self.assertEqual(second['research']['events'],[])
                saved=next(item for item in store.list_sessions() if item['id']==tab.session['id']);self.assertNotIn('secret-value',str(saved))
            finally:window.close();self.app.processEvents();store.db.close()

    def test_chat_task_required_tool_requires_capable_local_server(self):
        from agentnik.chat_mcp import ChatMCP
        from agentnik.tools import Runtime,ResearchError
        detail={'name':'work','description':'Work','description_clipped':False,'schema_status':'available','schema':{'type':'object'},'task_support':'required'}
        for remote,advertised,allowed in ((False,True,True),(False,False,False),(True,True,True),(True,False,False)):
            server={'name':'Test','transport':'http','url':'https://example.com/mcp','credential_id':'','enabled':True} if remote else {'name':'Test','command':sys.executable,'args':[],'enabled':True}
            controller=ChatMCP(server,{'mcp_servers':[server]});controller.bridge=Mock();controller.bridge.request.side_effect=[{'tool_details':[detail],'task_capabilities':{'tool_calls':advertised}},{'call_result':{'content':[{'type':'text','text':'done'}]}}]
            controller.invoke('mcp_discover',{'server':'connect'},Runtime());args={'request':json.dumps({'tool':'work','arguments':{}})}
            if allowed:self.assertIn('done',json.dumps(controller.invoke('mcp_call',args,Runtime())))
            else:
                with self.assertRaises(ResearchError):controller.invoke('mcp_call',args,Runtime())
                self.assertEqual(controller.bridge.request.call_count,1)

    def test_multiple_servers_use_ordered_precedence_and_batch_validation(self):
        from agentnik.chat_mcp import MultiChatMCP
        from agentnik.tools import Runtime,ResearchError
        servers=[{'name':name,'transport':'http','url':'https://example.com/mcp','credential_id':'','enabled':True} for name in ('First','Second','Third')]
        group=MultiChatMCP(servers,{'mcp_servers':servers});tool=lambda name:{'name':name,'description':name,'description_clipped':False,'schema_status':'available','schema':{'type':'object'}}
        for controller,tools in zip(group.controllers,([tool('shared'),tool('alpha')],[tool('shared'),tool('beta')],[tool('gamma')])):
            controller.bridge=Mock();controller.bridge.request.side_effect=[{'tool_details':tools},{'call_result':{'content':[{'type':'text','text':controller.server['name']}]}}]
        runtime=Runtime();runtime.calls=1
        result=group.invoke('mcp_discover',{'server':'connect'},runtime)
        self.assertEqual(runtime.calls,3);self.assertEqual([(item['name'],item['server']) for item in result['tools']],[('shared','First'),('alpha','First'),('beta','Second'),('gamma','Third')])
        def args(name,server=None):return {'request':json.dumps({'tool':name,'arguments':{},**({'server':server} if server else {})})}
        with self.assertRaisesRegex(ResearchError,'higher-priority'):group.validate_call('mcp_call',args('shared','Second'))
        with self.assertRaises(ResearchError):group.validate_batch([('mcp_call',args('alpha')),('mcp_call',args('missing'))])
        self.assertIn('First',json.dumps(group.invoke('mcp_call',args('shared'),runtime)))
        self.assertIn('Second',json.dumps(group.invoke('mcp_call',args('beta','Second'),runtime)))
        self.assertEqual(group.controllers[2].bridge.request.call_count,1)

    def test_multi_server_rejects_incomplete_or_unaffordable_discovery(self):
        from agentnik.chat_mcp import MultiChatMCP
        from agentnik.tools import Runtime,Limits,ResearchError
        servers=[{'name':name,'transport':'http','url':'https://example.com/mcp','credential_id':'','enabled':True} for name in ('First','Second')]
        group=MultiChatMCP(servers,{'mcp_servers':servers})
        for controller in group.controllers:controller.bridge=Mock();controller.bridge.request.return_value={'tool_details':[],'more_tools':True}
        runtime=Runtime(limits=Limits(calls=1));runtime.calls=1
        with self.assertRaisesRegex(ResearchError,'Not enough'):group.invoke('mcp_discover',{'server':'connect'},runtime)
        self.assertTrue(all(not controller.bridge.request.called for controller in group.controllers))
        runtime=Runtime();runtime.calls=1;group.invoke('mcp_discover',{'server':'connect'},runtime)
        with self.assertRaisesRegex(ResearchError,'incomplete'):group.validate_call('mcp_call',{'request':'{"tool":"anything","arguments":{}}'})

    def test_chat_server_picker_preserves_order_and_session(self):
        from PySide6.QtCore import Qt
        from PySide6.QtWidgets import QListWidget,QPushButton
        from agentnik.sessions import validate_session
        with tempfile.TemporaryDirectory() as folder,patch.object(core,'discover',return_value={}),patch.object(core,'environment_connections',return_value={}):
            store=Store(folder);store.config['mcp_servers']=[{'name':name,'command':sys.executable,'args':[],'enabled':True} for name in ('Parallel','Postgres','Subledger')];store.flush();window=Window(store);window.connections={'test':dict(C)}
            try:
                window.new_session('chat','test');tab=window.tabs.currentWidget()
                def select(dialog):
                    items=dialog.findChild(QListWidget,'chatMcpOrder')
                    for index in range(items.count()):items.item(index).setCheckState(Qt.CheckState.Checked)
                    items.setCurrentRow(2);dialog.findChild(QPushButton,'chatMcpMoveUp').click()
                    return QDialog.DialogCode.Accepted
                with patch.object(QDialog,'exec',select):tab.choose_chat_mcp_servers()
                self.assertEqual(tab.mcp_choice.currentData()['name'],'Parallel')
                self.assertEqual([item['name'] for item in tab.mcp_extra_refs],['Subledger','Postgres'])
                validate_session(tab.session)
                saved=next(item for item in store.list_sessions() if item['id']==tab.session['id'])
                self.assertEqual([item['name'] for item in saved['research_options']['mcp_extra']],['Subledger','Postgres'])
                tab.mcp_choice.setCurrentIndex(0);self.assertEqual(tab.mcp_extra_refs,[])
            finally:window.close();self.app.processEvents();store.db.close()

    def test_multi_server_chat_model_receives_each_server_result(self):
        import threading
        from agentnik.chat_mcp import MultiChatMCP
        servers=[{'name':name,'transport':'http','url':'https://example.com/mcp','credential_id':'','enabled':True} for name in ('Search','Database')]
        group=MultiChatMCP(servers,{'mcp_servers':servers});bodies=[]
        for controller,name in zip(group.controllers,('web_lookup','query')):
            tool={'name':name,'description':name,'description_clipped':False,'schema_status':'available','schema':{'type':'object'}}
            controller.bridge=Mock();controller.bridge.request.side_effect=[{'tool_details':[tool]},{'call_result':{'content':[{'type':'text','text':controller.server['name']+' result'}]}}]
        call=lambda name: {'request':json.dumps({'tool':name,'arguments':{}})}
        replies=[Wire(response([function('mcp_discover',{'server':'connect'},'first')]),False),Wire(response([function('mcp_call',call('web_lookup'),'second'),function('mcp_call',call('query'),'third')]),False),Wire(response([message('Done')]),False)]
        def send(connection,url,body,timeout):bodies.append(json.loads(json.dumps(body)));return replies.pop(0)
        with patch.object(core,'open_request',side_effect=send):result=research.run_managed(C,[{'role':'user','content':'Research'}],'',lambda _:None,threading.Event(),web_tools=False,mcp=group)
        self.assertEqual(result['status'],'ok',result);self.assertIn('Search result',json.dumps(bodies[-1]));self.assertIn('Database result',json.dumps(bodies[-1]))
        self.assertEqual([controller.bridge.request.call_count for controller in group.controllers],[2,2])

    def test_chat_runs_two_independent_local_mcp_servers(self):
        from agentnik.mcp_support import server_fingerprint
        with tempfile.TemporaryDirectory() as folder,patch.object(core,'discover',return_value={}),patch.object(core,'environment_connections',return_value={}),patch.object(core,'models',return_value=[]):
            root=Path(folder);server=root/'server.py'
            server.write_text('''import json,sys
for line in sys.stdin:
 req=json.loads(line);method=req['method']
 if method=='server/discover':print(json.dumps({'jsonrpc':'2.0','id':req['id'],'error':{'code':-32601,'message':'unsupported'}}),flush=True);continue
 if method=='notifications/initialized':continue
 if method=='initialize':result={'protocolVersion':req['params']['protocolVersion'],'serverInfo':{'name':sys.argv[1],'version':'1'},'capabilities':{'tools':{}}}
 elif method=='tools/list':result={'tools':[{'name':sys.argv[1],'inputSchema':{'type':'object'}}]}
 else:result={'content':[{'type':'text','text':sys.argv[1]+' evidence'}]}
 print(json.dumps({'jsonrpc':'2.0','id':req['id'],'result':result}),flush=True)
''',encoding='utf-8')
            store=Store(root/'data');servers=[{'name':name,'command':sys.executable,'args':[str(server),tool],'enabled':True} for name,tool in (('Search','find'),('Database','query'))];store.config['mcp_servers']=servers;store.flush()
            window=Window(store);window.connections={'test':dict(C)};bodies=[]
            request=lambda name: {'request':json.dumps({'tool':name,'arguments':{}})}
            replies=[Wire(response([function('mcp_discover',{'server':'connect'},'first')]),False),Wire(response([function('mcp_call',request('find'),'second'),function('mcp_call',request('query'),'third')]),False),Wire(response([message('Done')]),False)]
            def send(c,url,body,timeout):bodies.append(json.loads(json.dumps(body)));return replies.pop(0)
            try:
                window.new_session('chat','test');tab=window.tabs.currentWidget();tab.mcp_choice.setCurrentIndex(1);tab.mcp_extra_refs=[{'name':'Database','sha256':server_fingerprint(servers[1])}];tab.save_draft();tab.composer.setPlainText('Use both')
                with patch.object(core,'open_request',side_effect=send):tab.submit();self.settle(lambda:tab.job is None)
                self.assertEqual(tab.session['messages'][-1]['text'],'Done');self.assertIn('find evidence',json.dumps(bodies[-1]));self.assertIn('query evidence',json.dumps(bodies[-1]))
            finally:window.close();self.app.processEvents();store.db.close()

    def test_remote_controller_reviews_arguments_and_filters_user_content(self):
        from agentnik.chat_mcp import ChatMCP
        from agentnik.tools import Runtime
        server={'name':'Remote','transport':'http','url':'https://example.com/mcp','credential_id':'','enabled':True}
        controller=ChatMCP(server,{'mcp_servers':[server]});bridge=Mock();controller.bridge=bridge
        tool={'name':'query','description':'Query','description_clipped':False,'schema_status':'available','schema':{'type':'object','properties':{'q':{'type':'string'}},'required':['q']}}
        bridge.request.side_effect=[{'tool_details':[tool]},{'call_result':{'content':[{'type':'text','text':'private-for-user','annotations':{'audience':['user']}},{'type':'text','text':'model-evidence'}]}}]
        proposals=[]
        def accept(request):proposals.append(request['proposal']);request['approved']=True;request['done'].set()
        controller.approval_requested.connect(accept);runtime=Runtime();events=[];runtime.notify=lambda *args:events.append(args)
        controller.invoke('mcp_discover',{'server':'connect'},runtime)
        result=controller.invoke('mcp_call',{'request':json.dumps({'tool':'query','arguments':{'q':'abc'}})},runtime)
        self.assertEqual(proposals,[]);self.assertEqual(bridge.request.call_args_list[-1].args[1]['arguments'],{'q':'abc'})
        self.assertNotIn('private-for-user',json.dumps(result));self.assertIn('model-evidence',json.dumps(result));self.assertIn('private-for-user',str(events))
        self.assertEqual([entry.args[0] for entry in bridge.request.call_args_list],['discover','call'])

    def test_prompt_completion_uses_listed_server_prompt(self):
        from agentnik.chat_mcp import ChatMCP
        from agentnik.tools import Runtime
        server={'name':'Remote','transport':'http','url':'https://example.com/mcp','credential_id':'','enabled':True}
        controller=ChatMCP(server,{'mcp_servers':[server]});controller.bridge=Mock();controller.tools=[]
        controller.prompts=[{'name':'review','arguments':[{'name':'file'}]}]
        controller.bridge.request.return_value={'completion':{'values':['main.py']}}
        request={'server':'Remote','kind':'prompt','target':'review','argument':'file','value':'ma','context':{}}
        result=controller.invoke('mcp_complete_argument',{'request':json.dumps(request)},Runtime())
        self.assertEqual(result['completion']['values'],['main.py'])
        self.assertIn('untrusted',result['notice'].lower())
        self.assertEqual(controller.bridge.request.call_args.args[0],'complete')
        request['target']='unlisted'
        with self.assertRaises(Exception):controller.invoke('mcp_complete_argument',{'request':json.dumps(request)},Runtime())
        controller.bridge.request.assert_called_once()

    def test_tool_call_runs_without_approval(self):
        from agentnik.chat_mcp import ChatMCP
        from agentnik.tools import Runtime
        server={'name':'Remote','transport':'http','url':'https://example.com/mcp','credential_id':'','enabled':True}
        controller=ChatMCP(server,{'mcp_servers':[server]});bridge=Mock();controller.bridge=bridge
        controller.tools=[{'name':'query','description':'Query','description_clipped':False,'schema_status':'available','schema':{'type':'object'}}]
        def deny(request):request['approved']=False;request['done'].set()
        controller.approval_requested.connect(deny)
        bridge.request.return_value={'call_result':{'content':[]}}
        result=controller.invoke('mcp_call',{'request':json.dumps({'tool':'query','arguments':{}})},Runtime())
        self.assertIn('result',result);bridge.request.assert_called_once()

    def test_activity_names_tool_and_outcome_without_arguments_or_result(self):
        from agentnik.chat_mcp import ChatMCP
        from agentnik.tools import Runtime
        server={'name':'Remote','transport':'http','url':'https://example.com/mcp','credential_id':'','enabled':True}
        controller=ChatMCP(server,{'mcp_servers':[server]});controller.bridge=Mock()
        controller.tools=[{'name':'query','description':'Query','description_clipped':False,'schema_status':'available','schema':{'type':'object'}}]
        controller.bridge.request.side_effect=[{'call_result':{'content':[{'type':'text','text':'private-result'}]}},{'call_result':{'isError':True,'content':[{'type':'text','text':'private-error'}]}}]
        events=[];runtime=Runtime();runtime.notify=lambda kind,detail:events.append((kind,detail))
        for _ in range(2):controller.invoke('mcp_call',{'request':json.dumps({'tool':'query','arguments':{'sql':'private-query'}})},runtime)
        details='\n'.join(detail for _,detail in events)
        self.assertIn('Calling query on Remote.',details);self.assertIn('Tool query completed.',details);self.assertIn('Tool query reported an error.',details)
        self.assertNotIn('private-query',details);self.assertNotIn('private-result',details);self.assertNotIn('private-error',details)

    def test_activity_reports_uncertain_tool_call_without_retrying(self):
        from agentnik.chat_mcp import ChatMCP
        from agentnik.tools import Runtime,ResearchError
        server={'name':'Remote','transport':'http','url':'https://example.com/mcp','credential_id':'','enabled':True}
        controller=ChatMCP(server,{'mcp_servers':[server]});controller.bridge=Mock()
        controller.tools=[{'name':'write','description':'Write','description_clipped':False,'schema_status':'available','schema':{'type':'object'}}]
        controller.bridge.request.return_value={'error':'Connection closed','call_uncertain':True}
        events=[];runtime=Runtime();runtime.notify=lambda kind,detail:events.append(detail)
        with self.assertRaisesRegex(ResearchError,'may have completed'):
            controller.invoke('mcp_call',{'request':json.dumps({'tool':'write','arguments':{}})},runtime)
        controller.bridge.request.assert_called_once();self.assertIn('Tool write failed. The call may have completed; inspect server state before retrying.',events)

    def test_invalid_structured_output_reports_safe_reason_without_retry(self):
        from agentnik.chat_mcp import ChatMCP
        from agentnik.tools import Runtime,ResearchError
        server={'name':'Remote','transport':'http','url':'https://example.com/mcp','credential_id':'','enabled':True}
        controller=ChatMCP(server,{'mcp_servers':[server]});controller.bridge=Mock()
        controller.tools=[{'name':'search','description_clipped':False,'schema_status':'available','schema':{'type':'object'},'output_schema_status':'available','output_schema':{'type':'object'}}]
        controller.bridge.request.return_value={'call_result':{'content':[{'type':'text','text':'private-result'}]}}
        events=[];runtime=Runtime();runtime.notify=lambda kind,detail:events.append(detail)
        with self.assertRaisesRegex(ResearchError,'did not return a structured object'):
            controller.invoke('mcp_call',{'request':json.dumps({'tool':'search','arguments':{}})},runtime)
        controller.bridge.request.assert_called_once();self.assertNotIn('private-result',str(events));self.assertIn('may have completed',str(events))

    def test_nested_arguments_cannot_send_inference_or_mapped_credentials(self):
        from agentnik.chat_mcp import ChatMCP
        from agentnik.tools import Runtime,ResearchError
        secret='secret"with\\slashes'
        server={'name':'Remote','transport':'http','url':'https://example.com/mcp','credential_id':'','enabled':True}
        controller=ChatMCP(server,{'mcp_servers':[server]},extra_secrets=(secret,));bridge=Mock();controller.bridge=bridge
        controller.tools=[{'name':'query','description':'Query','description_clipped':False,'schema_status':'available','schema':{'type':'object'}}]
        with self.assertRaises(ResearchError):controller.invoke('mcp_call',{'request':json.dumps({'tool':'query','arguments':{'nested':{'value':secret}}})},Runtime())
        bridge.request.assert_not_called()

    def test_credentials_are_redacted_from_untrusted_object_keys(self):
        value={'content':[{'text':'prefix-secret-fixture','nested':{'secret-fixture':'secret-fixture'}}]}
        sanitized=research.scrub(value,('secret-fixture',))
        self.assertNotIn('secret-fixture',json.dumps(sanitized));self.assertIn('[redacted]',json.dumps(sanitized))

    def test_batch_validation_happens_before_server_actions(self):
        from agentnik.chat_mcp import ChatMCP
        from agentnik.tools import ResearchError
        server={'name':'Remote','transport':'http','url':'https://example.com/mcp','credential_id':'','enabled':True}
        controller=ChatMCP(server,{'mcp_servers':[server]});bridge=Mock();controller.bridge=bridge
        good={'request':json.dumps({'tool':'query','arguments':{'value':1}})}
        bad={'request':json.dumps({'tool':'query','arguments':{'value':'wrong'}})}
        with self.assertRaises(ResearchError):controller.validate_batch([('mcp_discover',{'server':'connect'}),('mcp_call',good)])
        controller.tools=[{'name':'query','description':'Query','description_clipped':False,'schema_status':'available','schema':{'type':'object','properties':{'value':{'type':'integer'}}}}]
        with self.assertRaises(ResearchError):controller.validate_batch([('mcp_call',good),('mcp_call',bad)])
        bridge.request.assert_not_called()

    def test_discovery_accepts_only_selected_server_name_or_connect(self):
        from agentnik.chat_mcp import ChatMCP
        from agentnik.tools import ResearchError
        server={'name':'Parquet','transport':'http','url':'https://example.com/mcp','credential_id':'','enabled':True}
        controller=ChatMCP(server,{'mcp_servers':[server]})
        for name in ('connect','Parquet','PARQUET'):
            controller.validate_batch([('mcp_discover',{'server':name})])
        with self.assertRaises(ResearchError):controller.validate_batch([('mcp_discover',{'server':'Other'})])

    def test_mcp_server_error_is_recorded_and_returned_to_model(self):
        import threading
        from agentnik.tools import ToolDefinition
        class FakeMCP:
            secret_values=[]
            definitions=(ToolDefinition('mcp_call','request','Call.',200),)
            def invoke(self,name,args,runtime):return {'result':{'isError':True,'content':[{'type':'text','text':'fixture failure'}]},'notice':'fixture'}
            def validate_batch(self,calls):pass
        bodies=[]
        replies=[Wire(response([function('mcp_call',{'request':'{}'},'first')]),False),Wire(response([message('The query failed.')]),False)]
        def send(c,url,body,timeout):bodies.append(body);return replies.pop(0)
        with patch.object(core,'open_request',side_effect=send):
            result=research.run_managed(C,[{'role':'user','content':'Query'}],'',lambda _:None,threading.Event(),web_tools=False,mcp=FakeMCP())
        self.assertEqual(result['status'],'ok')
        self.assertEqual(result['research']['tool_records'][0]['status'],'failed')
        self.assertIn('tool_failed',[event['kind'] for event in result['research']['events']])
        self.assertIn('fixture failure',json.dumps(bodies[-1]))

    def test_invalid_batch_is_not_executed_and_model_can_correct_it(self):
        import threading
        from agentnik.chat_mcp import ChatMCP
        server={'name':'Remote','transport':'http','url':'https://example.com/mcp','credential_id':'','enabled':True}
        tool={'name':'query','description':'Query','description_clipped':False,'schema_status':'available','schema':{'type':'object','properties':{'value':{'type':'integer'}},'required':['value']}}
        for reconnect in (False,True):
            with self.subTest(reconnect=reconnect):
                controller=ChatMCP(server,{'mcp_servers':[server]});bridge=Mock();controller.bridge=bridge
                if reconnect:bridge.request.side_effect=[{'tool_details':[tool]},{'call_result':{'content':[{'type':'text','text':'ok'}]}}]
                else:controller.tools=[tool];bridge.request.return_value={'call_result':{'content':[{'type':'text','text':'ok'}]}}
                good=json.dumps({'tool':'query','arguments':{'value':1}});bad=json.dumps({'tool':'query','arguments':{'value':'bad'}})
                replies=[Wire(response([function('mcp_call',{'request':good},'first'),function('mcp_call',{'request':bad},'second')]),False),Wire(response([function('mcp_call',{'request':good},'corrected')]),False),Wire(response([message('Done')]),False)]
                bodies=[]
                def send(c,url,body,timeout):bodies.append(json.loads(json.dumps(body)));return replies.pop(0)
                with patch.object(core,'open_request',side_effect=send):
                    result=research.run_managed(C,[{'role':'user','content':'Query'}],'',lambda _:None,threading.Event(),web_tools=False,mcp=controller)
                self.assertEqual(result['status'],'ok');self.assertEqual(result['text'],'Done')
                self.assertEqual([entry.args[0] for entry in bridge.request.call_args_list],(['discover','call'] if reconnect else ['call']))
                self.assertIn('No tools in this batch were executed',json.dumps(bodies[1]))
                self.assertEqual([r['status'] for r in result['research']['tool_records']],['failed','failed','completed'])

    def test_wrong_outer_argument_shape_is_returned_to_model(self):
        import threading
        from agentnik.chat_mcp import ChatMCP
        server={'name':'Remote','transport':'http','url':'https://example.com/mcp','credential_id':'','enabled':True}
        controller=ChatMCP(server,{'mcp_servers':[server]});controller.bridge=Mock()
        wrong={'request':{'tool':'query','arguments':{}}}
        replies=[Wire(response([function('mcp_call',wrong,'first')]),False),Wire(response([message('I could not form the request.')]),False)];bodies=[]
        def send(c,url,body,timeout):bodies.append(json.loads(json.dumps(body)));return replies.pop(0)
        with patch.object(core,'open_request',side_effect=send):
            result=research.run_managed(C,[{'role':'user','content':'Query'}],'',lambda _:None,threading.Event(),web_tools=False,mcp=controller)
        self.assertEqual(result['status'],'ok');controller.bridge.request.assert_not_called()
        self.assertIn('Invalid request',json.dumps(bodies[-1]));self.assertEqual(result['research']['tool_records'][0]['status'],'failed')

    def test_mcp_continuation_across_other_chat_protocols(self):
        import threading
        from agentnik.tools import ToolDefinition
        from test_research import C as native,MESSAGES,Response,answer,call
        from test_compat_tools import chat,msg,chat_call
        class FakeMCP:
            secret_values=[]
            definitions=(ToolDefinition('mcp_discover','server','Connect.',200),)
            def invoke(self,name,args,runtime):return {'tools':['fixture']}
            def validate_batch(self,calls):pass
        one=chat_call();one['function'].update(name='mcp_discover',arguments='{"server":"connect"}')
        block={'type':'tool_use','id':'call-1','name':'mcp_discover','input':{'server':'connect'}}
        fixtures=[(dict(native,stream=False),[Response([answer('',[call('mcp_discover',{'server':'connect'})])],False),Response([answer('Done')],False)]),
                  ({'url':'https://example.com/v1','protocol':'chat','model':'test','stream':False},[Wire(chat(calls=[one],finish='tool_calls'),False),Wire(chat('Done'),False)]),
                  ({'url':'https://example.com/v1','protocol':'messages','model':'test','stream':False},[Wire(msg([block],'tool_use'),False),Wire(msg([{'type':'text','text':'Done'}]),False)])]
        for connection,replies in fixtures:
            with self.subTest(protocol=connection['protocol'],url=connection['url']),patch.object(core,'open_request',side_effect=replies):
                result=research.run_managed(connection,MESSAGES,'',lambda _:None,threading.Event(),web_tools=False,mcp=FakeMCP())
                self.assertEqual(result['status'],'ok');self.assertEqual(result['text'],'Done')

    def test_partial_mcp_result_continues_across_other_chat_protocols(self):
        import threading
        from agentnik.tools import Limits,ToolDefinition
        from test_research import C as native,MESSAGES,Response,answer,call
        from test_compat_tools import chat,msg,chat_call
        class FakeMCP:
            secret_values=[]
            definitions=(ToolDefinition('mcp_discover','server','Connect.',200),)
            def __init__(self):self.count=0
            def invoke(self,name,args,runtime):self.count+=1;return {'text':'Evidence '*5000}
            def validate_batch(self,calls):pass
        one=chat_call();one['function'].update(name='mcp_discover',arguments='{"server":"connect"}')
        block={'type':'tool_use','id':'call-1','name':'mcp_discover','input':{'server':'connect'}}
        fixtures=[(dict(native,stream=False),[Response([answer('',[call('mcp_discover',{'server':'connect'})])],False),Response([answer('Done')],False)]),
                  ({'url':'https://example.com/v1','protocol':'chat','model':'test','stream':False},[Wire(chat(calls=[one],finish='tool_calls'),False),Wire(chat('Done'),False)]),
                  ({'url':'https://example.com/v1','protocol':'messages','model':'test','stream':False},[Wire(msg([block],'tool_use'),False),Wire(msg([{'type':'text','text':'Done'}]),False)])]
        for connection,replies in fixtures:
            bodies=[];mcp=FakeMCP()
            def send(c,url,body,timeout):bodies.append(json.loads(json.dumps(body)));return replies.pop(0)
            with self.subTest(protocol=connection['protocol'],url=connection['url']),patch.object(core,'open_request',side_effect=send):
                result=research.run_managed(connection,MESSAGES,'',lambda _:None,threading.Event(),limits=Limits(context_bytes=6000),web_tools=False,mcp=mcp)
                self.assertEqual(result['status'],'ok');self.assertEqual(mcp.count,1);self.assertIn('partial, untrusted JSON preview',json.dumps(bodies[-1]))

    def test_invalid_call_feedback_continues_across_chat_protocols(self):
        import threading
        from agentnik.tools import ToolDefinition,ResearchError
        from test_research import C as native,MESSAGES,Response,answer,call
        from test_compat_tools import chat,msg,chat_call
        class InvalidMCP:
            secret_values=[]
            definitions=(ToolDefinition('mcp_call','request','Call.',200),)
            def validate_batch(self,calls):raise ResearchError('Invalid fixture request')
            def invoke(self,*args):self.fail('Invalid request must not execute')
        one=chat_call();one['function'].update(name='mcp_call',arguments='{"request":"{}"}')
        block={'type':'tool_use','id':'call-1','name':'mcp_call','input':{'request':'{}'}}
        fixtures=[(dict(native,stream=False),[Response([answer('',[call('mcp_call',{'request':'{}'})])],False),Response([answer('Done')],False)]),
                  ({'url':'https://example.com/v1','protocol':'chat','model':'test','stream':False},[Wire(chat(calls=[one],finish='tool_calls'),False),Wire(chat('Done'),False)]),
                  ({'url':'https://example.com/v1','protocol':'messages','model':'test','stream':False},[Wire(msg([block],'tool_use'),False),Wire(msg([{'type':'text','text':'Done'}]),False)])]
        for connection,replies in fixtures:
            bodies=[]
            def send(c,url,body,timeout):bodies.append(json.loads(json.dumps(body)));return replies.pop(0)
            with self.subTest(protocol=connection['protocol'],url=connection['url']),patch.object(core,'open_request',side_effect=send):
                result=research.run_managed(connection,MESSAGES,'',lambda _:None,threading.Event(),web_tools=False,mcp=InvalidMCP())
                self.assertEqual(result['status'],'ok');self.assertEqual(result['text'],'Done')
                self.assertIn('Invalid fixture request',json.dumps(bodies[-1]))

    def test_mcp_images_continue_across_other_chat_protocols(self):
        import base64,threading
        from agentnik.tools import ToolDefinition
        from test_image_generation import png
        from test_research import C as native,MESSAGES,Response,answer,call
        from test_compat_tools import chat,msg,chat_call
        data=png();encoded=base64.b64encode(data).decode('ascii')
        class FakeMCP:
            secret_values=[]
            definitions=(ToolDefinition('mcp_discover','server','Connect.',200),)
            def __init__(self):self.images=[]
            def invoke(self,name,args,runtime):self.images=[('MCP image',data,'image/png')];return {'notice':'image follows'}
            def validate_batch(self,calls):pass
            def take_images(self):images=self.images;self.images=[];return images
        one=chat_call();one['function'].update(name='mcp_discover',arguments='{"server":"connect"}')
        block={'type':'tool_use','id':'call-1','name':'mcp_discover','input':{'server':'connect'}}
        fixtures=[(dict(native,stream=False),[Response([answer('',[call('mcp_discover',{'server':'connect'})])],False),Response([answer('Done')],False)]),
                  ({'url':'https://example.com/v1','protocol':'chat','model':'test','stream':False},[Wire(chat(calls=[one],finish='tool_calls'),False),Wire(chat('Done'),False)]),
                  ({'url':'https://example.com/v1','protocol':'messages','model':'test','stream':False},[Wire(msg([block],'tool_use'),False),Wire(msg([{'type':'text','text':'Done'}]),False)])]
        for connection,replies in fixtures:
            bodies=[]
            def send(c,url,body,timeout):bodies.append(json.loads(json.dumps(body)));return replies.pop(0)
            with self.subTest(protocol=connection['protocol'],url=connection['url']),patch.object(core,'open_request',side_effect=send):
                result=research.run_managed(connection,MESSAGES,'',lambda _:None,threading.Event(),web_tools=False,mcp=FakeMCP())
                self.assertEqual(result['status'],'ok');self.assertIn(encoded,json.dumps(bodies[-1]));self.assertNotIn(encoded,json.dumps(result))
                self.assertEqual(bodies[-1]['messages'][-1]['role'],'user')

    def test_approved_responses_turn_persists_and_reopens_without_server_restart(self):
        with tempfile.TemporaryDirectory() as folder,patch.object(core,'discover',return_value={}),patch.object(core,'environment_connections',return_value={}),patch.object(core,'models',return_value=[]):
            root=Path(folder);marker=root/'calls';server=root/'server.py'
            server.write_text('''import json,sys,pathlib
for line in sys.stdin:
 req=json.loads(line);method=req['method']
 if method=='server/discover':print(json.dumps({'jsonrpc':'2.0','id':req['id'],'error':{'code':-32601,'message':'unsupported'}}),flush=True);continue
 if method=='notifications/initialized':continue
 if method=='initialize':result={'protocolVersion':req['params']['protocolVersion'],'serverInfo':{'name':'Fake','version':'1'},'capabilities':{'tools':{}}}
 elif method=='tools/list':result={'tools':[{'name':'count','description':'Count rows','inputSchema':{'type':'object','properties':{'table':{'type':'string'}},'required':['table']}}]}
 else:
  pathlib.Path(sys.argv[1]).write_text('called');result={'content':[{'type':'text','text':'Count: 42'}]}
 print(json.dumps({'jsonrpc':'2.0','id':req['id'],'result':result}),flush=True)
''',encoding='utf-8')
            store=Store(root/'data');store.config['mcp_servers']=[{'name':'Database','command':sys.executable,'args':[str(server),str(marker)],'enabled':True}];store.flush()
            window=Window(store);window.connections={'test':dict(C)};bodies=[]
            request=json.dumps({'tool':'count','arguments':{'table':'ap'}})
            replies=[Wire(response([function('mcp_discover',{'server':'Database'},'first')]),False),Wire(response([function('mcp_call',{'request':request},'second')]),False),Wire(response([message('There are 42 rows.')]),False)]
            def send(c,url,body,timeout):bodies.append(json.loads(json.dumps(body)));return replies.pop(0)
            try:
                window.new_session('chat','test');tab=window.tabs.currentWidget();tab.mcp_choice.setCurrentIndex(1)
                self.assertFalse(marker.exists());tab.composer.setPlainText('Count AP rows')
                with patch.object(core,'open_request',side_effect=send),patch.object(QDialog,'exec',return_value=QDialog.DialogCode.Accepted) as approvals:
                    tab.submit();self.settle(lambda:tab.job is None)
                self.assertEqual(approvals.call_count,0);self.assertTrue(marker.exists());self.assertEqual(tab.session['messages'][-1]['text'],'There are 42 rows.')
                self.assertIn('Count: 42',json.dumps(bodies[-1]));self.assertEqual(tab.session['messages'][-1]['research']['status'],'completed')
                marker.unlink();tab.composer.setPlainText('Count again')
                replies.extend([Wire(response([function('mcp_call',{'request':request},'third')]),False),Wire(response([message('Still 42 rows.')]),False)])
                with patch.object(core,'open_request',side_effect=send),patch.object(QDialog,'exec',return_value=QDialog.DialogCode.Accepted) as approvals:
                    tab.submit();self.settle(lambda:tab.job is None)
                self.assertEqual(approvals.call_count,0);self.assertTrue(marker.exists());self.assertEqual(tab.session['messages'][-1]['text'],'Still 42 rows.')
                self.assertIn('Reconnecting',str(tab.session['messages'][-1]['research']['events']))
                from agentnik.research_ui import ResearchDetails
                details=tab.findChildren(ResearchDetails)[-1]
                self.assertIn('MCP activity',details.toggle.text());self.assertIn('Calling count on Database.',details.activity.toPlainText());self.assertIn('Tool count completed.',details.activity.toPlainText())
                saved=next(item for item in store.list_sessions() if item['id']==tab.session['id'])
                marker.unlink();window.close_tab(window.tabs.indexOf(tab));window.open_session(saved);self.app.processEvents()
                self.assertFalse(marker.exists());self.assertEqual(window.tabs.currentWidget().mcp_choice.currentData()['name'],'Database')
            finally:window.close();self.app.processEvents();store.db.close()

    def test_large_tool_result_reaches_model_and_survives_followup(self):
        with tempfile.TemporaryDirectory() as folder,patch.object(core,'discover',return_value={}),patch.object(core,'environment_connections',return_value={}),patch.object(core,'models',return_value=[]):
            root=Path(folder);server=root/'server.py'
            server.write_text('''import json,sys
for line in sys.stdin:
 req=json.loads(line);method=req['method']
 if method=='server/discover':print(json.dumps({'jsonrpc':'2.0','id':req['id'],'error':{'code':-32601,'message':'unsupported'}}),flush=True);continue
 if method=='notifications/initialized':continue
 if method=='initialize':result={'protocolVersion':req['params']['protocolVersion'],'serverInfo':{'name':'Fake','version':'1'},'capabilities':{'tools':{}}}
 elif method=='tools/list':result={'tools':[{'name':'query','inputSchema':{'type':'object'}}]}
 else:result={'content':[{'type':'text','text':'x'*500000+'END'}]}
 print(json.dumps({'jsonrpc':'2.0','id':req['id'],'result':result}),flush=True)
''',encoding='utf-8')
            store=Store(root/'data');store.config['mcp_servers']=[{'name':'Database','command':sys.executable,'args':[str(server)],'enabled':True}];store.flush()
            window=Window(store);window.connections={'test':dict(C)};bodies=[];request=json.dumps({'tool':'query','arguments':{}})
            replies=[Wire(response([function('mcp_discover',{'server':'Database'},'first')]),False),Wire(response([function('mcp_call',{'request':request},'second')]),False),Wire(response([message('Done')]),False),Wire(response([message('Follow-up')]),False)]
            def send(c,url,body,timeout):bodies.append(json.dumps(body));return replies.pop(0)
            try:
                window.new_session('chat','test');tab=window.tabs.currentWidget();tab.mcp_choice.setCurrentIndex(1);tab.composer.setPlainText('Query')
                with patch.object(core,'open_request',side_effect=send):
                    tab.submit();self.settle(lambda:tab.job is None)
                    self.assertEqual(tab.session['messages'][-1]['status'],'ok');self.assertIn('x'*500000+'END',bodies[-1])
                    tab.composer.setPlainText('Follow up');tab.submit();self.settle(lambda:tab.job is None)
                self.assertEqual(tab.session['messages'][-1]['text'],'Follow-up');self.assertIn('x'*500000+'END',bodies[-1])
            finally:window.close();self.app.processEvents();store.db.close()

    def test_global_mcp_switch_preserves_selection_and_excludes_server(self):
        with tempfile.TemporaryDirectory() as folder,patch.object(core,'discover',return_value={}),patch.object(core,'environment_connections',return_value={}),patch.object(core,'models',return_value=[]):
            store=Store(folder);store.config['mcp_servers']=[{'name':'Local','command':sys.executable,'args':[],'enabled':True}];store.flush();window=Window(store);window.connections={'test':dict(C)}
            try:
                window.new_session('chat','test');tab=window.tabs.currentWidget();tab.mcp_choice.setCurrentIndex(1);selected=tab.mcp_choice.currentData();window.mcp_access.setChecked(False);tab.composer.setPlainText('Question')
                result={'text':'Done','thinking':'','metrics':{},'status':'ok','research':{'status':'completed','route':'managed','sources':[],'events':[],'exchanges':[]}}
                with patch('agentnik.chat_mcp.ChatMCP') as controller,patch('agentnik.research.run',return_value=result) as run:
                    tab.submit();self.settle(lambda:tab.job is None);controller.assert_not_called();self.assertIsNone(run.call_args.kwargs['mcp'])
                self.assertEqual(tab.mcp_choice.currentData(),selected);window.mcp_access.setChecked(True);self.assertEqual(tab.mcp_choice.currentData(),selected)
            finally:window.close();self.app.processEvents();store.db.close()

    def test_stale_selection_and_strict_navigation_do_not_submit(self):
        with tempfile.TemporaryDirectory() as folder,patch.object(core,'discover',return_value={}),patch.object(core,'environment_connections',return_value={}),patch.object(core,'models',return_value=[]):
            store=Store(folder);server={'name':'Local','command':sys.executable,'args':[],'enabled':True};store.config['mcp_servers']=[server];store.flush()
            window=Window(store);window.connections={'test':dict(C)}
            try:
                window.new_session('chat','test');tab=window.tabs.currentWidget();tab.mcp_choice.setCurrentIndex(1);tab.composer.setPlainText('Run')
                server['args']=['changed']
                with patch('agentnik.ui.error') as warning,patch.object(core,'open_request') as send:
                    tab.submit();self.assertIn('changed',str(warning.call_args.args[1]));send.assert_not_called()
                tab.refresh_chat_mcp();tab.mcp_choice.setCurrentIndex(1)
                from agentnik import routing
                store.config['settings']['research_access_policy']='strict_public'
                with patch('agentnik.ui.error') as warning,patch.object(core,'open_request') as send:
                    tab.submit();self.assertIn('Strict public-only',str(warning.call_args.args[1]));send.assert_not_called()
            finally:window.close();self.app.processEvents();store.db.close()


    def test_read_only_unknown_and_write_tools_need_no_approval(self):
        from agentnik.chat_mcp import ChatMCP
        from agentnik.tools import Runtime
        server={'name':'Remote','transport':'http','url':'https://example.com/mcp','credential_id':'','enabled':True}
        controller=ChatMCP(server,{'mcp_servers':[server]});bridge=Mock();controller.bridge=bridge
        def tool(name,annotations):return {'name':name,'description':'Fixture','description_clipped':False,'schema_status':'available','schema':{'type':'object'},'annotations':annotations}
        controller.tools=[tool('read',{'readOnlyHint':True}),tool('write',{'readOnlyHint':False}),tool('unknown',{})]
        bridge.request.return_value={'call_result':{'content':[]}}
        proposals=[]
        def deny(request):proposals.append(request['proposal']);request['approved']=False;request['done'].set()
        controller.approval_requested.connect(deny)
        for name in ('read','write','unknown'):
            controller.invoke('mcp_call',{'request':json.dumps({'tool':name,'arguments':{}})},Runtime())
        self.assertEqual(proposals,[]);self.assertEqual(bridge.request.call_count,3)
