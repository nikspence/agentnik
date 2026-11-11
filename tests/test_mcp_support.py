import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from agentnik.mcp_support import PROTOCOL,parse_initialize,validate_servers
from agentnik.storage import Store,load_config,ConfigurationError


class MCPFoundation(unittest.TestCase):
    def test_argument_schema_validation_and_unsupported_features(self):
        from agentnik.mcp_schema import validate_tool_arguments
        schema={'type':'object','properties':{'query':{'type':'string'},'n':{'type':'integer','minimum':1}},'required':['query'],'additionalProperties':False}
        self.assertTrue(validate_tool_arguments(schema,{'query':'MCP','n':2}))
        for arguments in ({},{'query':3},{'query':'ok','n':0},{'query':'ok','extra':True}):
            with self.subTest(arguments=arguments),self.assertRaisesRegex(ValueError,'do not match'):validate_tool_arguments(schema,arguments)
        self.assertTrue(validate_tool_arguments({'type':'object','properties':{'database':{'anyOf':[{'type':'string'},{'type':'null'}]}}},{'database':None}))
        for unsafe in ({'type':'object','$ref':'https://example.com/schema'},{'type':'object','properties':{'q':{'type':'string','pattern':'(a+)+$'}}}):
            with self.subTest(schema=unsafe),self.assertRaisesRegex(ValueError,'unsupported'):validate_tool_arguments(unsafe,{})
        with self.assertRaisesRegex(ValueError,'invalid'):validate_tool_arguments({'type':'object','required':'query'}, {})

    def test_schema_local_definitions_unions_and_bounds(self):
        from agentnik.mcp_schema import validate_tool_arguments
        schema={'type':'object','$defs':{
            'record':{'type':'object','properties':{'id':{'type':'integer','minimum':1}},'required':['id'],'additionalProperties':False},
            'alias/name':{'type':'string','minLength':1}},
            'properties':{'item':{'$ref':'#/$defs/record'},'name':{'$ref':'#/$defs/alias~1name'},
                          'mode':{'oneOf':[{'const':'quick'},{'const':'full'}]},
                          'value':{'anyOf':[{'type':'integer'},{'type':'string'},{'type':'null'}]}},
            'allOf':[{'required':['item','name']},{'required':['mode']}],'additionalProperties':False}
        self.assertTrue(validate_tool_arguments(schema,{'item':{'id':3},'name':'sample','mode':'quick','value':None}))
        for arguments in ({'item':{'id':0},'name':'sample','mode':'quick'},{'item':{'id':1},'name':'sample','mode':'other'},{'item':{'id':1},'name':'','mode':'full'}):
            with self.subTest(arguments=arguments),self.assertRaisesRegex(ValueError,'do not match'):validate_tool_arguments(schema,arguments)
        cyclic={'type':'object','$defs':{'x':{'$ref':'#/$defs/y'},'y':{'$ref':'#/$defs/x'}},'properties':{'x':{'$ref':'#/$defs/x'}}}
        with self.assertRaisesRegex(ValueError,'recursive'):validate_tool_arguments(cyclic,{})
        for reference in ('https://example.com/s.json','#','file:///secret','#/$defs/missing','#/$defs/a%2Fb','#/$defs/a~2b','#/$defs/a/extra'):
            with self.subTest(reference=reference),self.assertRaises(ValueError):validate_tool_arguments({'type':'object','$defs':{'a':{'type':'string'}},'properties':{'x':{'$ref':reference}}},{})
        broad={'type':'object','properties':{'x':{'anyOf':[{'anyOf':[{'const':n} for n in range(8)]} for _ in range(8)]}}}
        with self.assertRaisesRegex(ValueError,'complex'):validate_tool_arguments(broad,{})
        with self.assertRaises(ValueError):validate_tool_arguments({'type':'object','allOf':[]},{})

    def test_configuration_validation_and_persistence(self):
        item={'name':'Local','command':sys.executable,'args':['server.py'],'enabled':True}
        with tempfile.TemporaryDirectory() as folder:
            store=Store(folder)
            try:store.config['mcp_servers']=[item];store.flush();self.assertEqual(load_config(store.config_path)['mcp_servers'],[item])
            finally:store.db.close()
            for invalid in ([item,item],[dict(item,args='unsafe')],[dict(item,enabled=1)],[dict(item,api_key='secret')]):
                with self.assertRaises(ValueError):validate_servers(invalid)
            Path(folder,'connections.json').write_text(json.dumps({'version':1,'connections':{},'settings':{},'mcp_servers':[dict(item,args='bad')]}),encoding='utf-8')
            with self.assertRaises(ConfigurationError):load_config(Path(folder,'connections.json'))

    def test_local_environment_references_validate_and_persist_names_only(self):
        from agentnik.mcp_support import resolve_environment_references
        item={'name':'Env','command':sys.executable,'args':[],'env':{'TARGET_TOKEN':'AGENTNIK_TEST_MCP_TOKEN'},'enabled':True}
        with tempfile.TemporaryDirectory() as folder,patch.dict(os.environ,{'AGENTNIK_TEST_MCP_TOKEN':'secret-fixture-value'}):
            store=Store(folder)
            try:
                store.config['mcp_servers']=[item];store.flush();saved=store.config_path.read_text(encoding='utf-8')
                self.assertNotIn('secret-fixture-value',saved);self.assertEqual(load_config(store.config_path)['mcp_servers'],[item]);self.assertEqual(resolve_environment_references(item['env'])['TARGET_TOKEN'],'secret-fixture-value')
            finally:store.db.close()
        for mapping in ({'BAD=NAME':'SOURCE'},{'GOOD':'literal value'},{'A':'SOURCE','a':'OTHER'},['bad'],{'X':123}):
            with self.subTest(mapping=mapping),self.assertRaises(ValueError):validate_servers([dict(item,env=mapping)])
        with patch.dict(os.environ,{},clear=True):
            with self.assertRaisesRegex(ValueError,'missing'):resolve_environment_references({'TOKEN':'AGENTNIK_MISSING_TEST'})

    def test_local_mcp_environment_mapping_hides_values_and_blocks_reflection(self):
        os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
        from PySide6.QtCore import QEventLoop,QTimer
        from PySide6.QtWidgets import QApplication
        from agentnik.mcp_local import LocalSession
        app=QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as folder,patch.dict(os.environ,{'AGENTNIK_TEST_MCP_TOKEN':'secret-fixture-value'}):
            server=Path(folder)/'server.py'
            server.write_text('''import json,os,sys
for line in sys.stdin:
 req=json.loads(line);method=req['method']
 if method=='notifications/initialized':continue
 if method=='initialize':result={'protocolVersion':req['params']['protocolVersion'],'serverInfo':{'name':'mapped' if os.environ.get('TARGET_TOKEN')==os.environ.get('AGENTNIK_TEST_MCP_TOKEN') else 'missing','version':'1'},'capabilities':{'tools':{}}}
 elif method=='tools/list':result={'tools':[{'name':'echo','inputSchema':{'type':'object'}}]}
 else:result={'content':[{'type':'text','text':os.environ['TARGET_TOKEN']}]}
 print(json.dumps({'jsonrpc':'2.0','id':req['id'],'result':result}),flush=True)
''',encoding='utf-8')
            session=LocalSession(sys.executable,[str(server)],env_refs={'TARGET_TOKEN':'AGENTNIK_TEST_MCP_TOKEN'});loop=QEventLoop();results=[]
            def discovered(info):results.append(info);session.call(info['tool_details'][0],{})
            session.discovered.connect(discovered);session.ended.connect(lambda result:(results.append(result),loop.quit()));session.start();QTimer.singleShot(5000,loop.quit);loop.exec();session.close()
            self.assertEqual(results[0]['name'],'mapped');self.assertIn('mapped environment value',results[1]['error']);self.assertTrue(results[1]['call_uncertain']);self.assertNotIn('secret-fixture-value',str(results))

    def test_protocol_response_validation(self):
        result={'jsonrpc':'2.0','id':1,'result':{'protocolVersion':PROTOCOL,'serverInfo':{'name':'Example','version':'1'},'capabilities':{'tools':{},'resources':{}}}}
        self.assertEqual(parse_initialize(json.dumps(result).encode())['capabilities'],['tools','resources'])
        older=dict(result,result=dict(result['result'],protocolVersion='2024-11-05'))
        self.assertEqual(parse_initialize(json.dumps(older).encode(),(PROTOCOL,'2024-11-05'))['protocol'],'2024-11-05')
        for message in (b'not json',json.dumps(dict(result,id=True)).encode(),json.dumps(dict(result,result={'protocolVersion':'different'})).encode()):
            with self.assertRaises(ValueError):parse_initialize(message)

    def test_remote_validation_and_sse_messages(self):
        from agentnik.mcp_remote import response_message,preview_tool
        remote={'name':'Parallel','transport':'http','url':'https://mcp.parallel.ai/mcp','credential_id':'opaque','enabled':True}
        validate_servers([remote])
        for url in ('http://example.com/mcp','https://user:secret@example.com/mcp','https://example.com/mcp?key=secret'):
            with self.assertRaises(ValueError):validate_servers([dict(remote,url=url)])
        body=b': keepalive\n\ndata: {"jsonrpc":"2.0","id":1,"result":{}}\n\n'
        self.assertEqual(response_message(body,'text/event-stream',1)['id'],1)
        with self.assertRaises(ValueError):response_message(body+body,'text/event-stream',1)
        with self.assertRaises(ValueError):response_message(b'{"jsonrpc":"2.0","id":9}','application/json',1)
        detail=preview_tool({'description':'Search','inputSchema':{'type':'object'}})
        self.assertEqual(detail['schema'],{'type':'object'});self.assertEqual(detail['schema_status'],'available')
        self.assertEqual(preview_tool({'description':'x'*9000,'inputSchema':{'long':'a'*33000}})['schema_status'],'oversized')
        self.assertTrue(preview_tool({'description':'x'*9000})['description_clipped'])
        self.assertEqual(preview_tool({})['schema_status'],'missing')
        self.assertEqual(preview_tool({'execution':{'taskSupport':'required'}})['task_support'],'required')
        with self.assertRaises(ValueError):preview_tool({'execution':{'taskSupport':'unknown'}})
        with self.assertRaises(ValueError):preview_tool({'inputSchema':[]})

    def test_remote_session_and_discovery_with_fake_server(self):
        import threading
        from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
        os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
        from PySide6.QtCore import QEventLoop,QTimer
        from PySide6.QtWidgets import QApplication
        from agentnik.mcp_remote import RemoteProbe
        calls=[]
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def do_POST(self):
                body=json.loads(self.rfile.read(int(self.headers['Content-Length'])));calls.append((body['method'],self.headers.get('Mcp-Session-Id'),self.headers.get('MCP-Protocol-Version'),self.headers.get('Authorization')))
                method=body['method']
                if method=='notifications/initialized':self.send_response(202);self.end_headers();return
                if method=='tools/call' and body['params']['arguments'].get('query')=='uncertain':self.connection.close();return
                if method=='initialize':result={'protocolVersion':PROTOCOL,'serverInfo':{'name':'Fake','version':''},'capabilities':{'tools':{}}}
                elif method=='tools/call':result={'content':[{'type':'text','text':'A search result'}],'isError':False}
                elif not body.get('params',{}).get('cursor'):result={'tools':[{'name':'web_search','description':'Search the web','inputSchema':{'type':'object','properties':{'query':{'type':'string'}}}}],'nextCursor':'page-2'}
                else:result={'tools':[{'name':'web_fetch','inputSchema':{'type':'object'}}]}
                payload=('data: '+json.dumps({'jsonrpc':'2.0','id':body['id'],'result':result})+'\n\n').encode()
                self.send_response(200);self.send_header('Content-Type','text/event-stream');self.send_header('Content-Length',str(len(payload)));self.send_header('Mcp-Session-Id','session-1');self.end_headers();self.wfile.write(payload)
            def do_DELETE(self):
                calls.append(('DELETE',self.headers.get('Mcp-Session-Id'),self.headers.get('MCP-Protocol-Version'),self.headers.get('Authorization')));self.send_response(204);self.end_headers()
        app=QApplication.instance() or QApplication([]);server=ThreadingHTTPServer(('127.0.0.1',0),Handler);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        try:
            loop=QEventLoop();probe=RemoteProbe('http://127.0.0.1:'+str(server.server_port)+'/mcp','test-token');results=[]
            probe.finished.connect(lambda result:(results.append(result),loop.quit()));probe.start();QTimer.singleShot(5000,loop.quit);loop.exec()
            self.assertEqual(results[0]['tools'],['web_search','web_fetch']);self.assertEqual(results[0]['version'],'unknown');self.assertTrue(results[0]['session_closed'])
            self.assertEqual(results[0]['tool_details'][0]['description'],'Search the web');self.assertIn('query',results[0]['tool_details'][0]['schema']['properties'])
            self.assertEqual([call[0] for call in calls],['initialize','notifications/initialized','tools/list','tools/list','DELETE'])
            self.assertTrue(all(call[1:3]==('session-1',PROTOCOL) for call in calls[1:]));self.assertTrue(all(call[3]=='Bearer test-token' for call in calls))
            loop2=QEventLoop();probe2=RemoteProbe('http://127.0.0.1:'+str(server.server_port)+'/mcp','test-token',invocation={'tool':results[0]['tool_details'][0],'arguments':{'query':'MCP'}});calls_result=[]
            probe2.finished.connect(lambda result:(calls_result.append(result),loop2.quit()));probe2.start();QTimer.singleShot(5000,loop2.quit);loop2.exec()
            self.assertEqual(calls_result[0]['call_result']['content'][0]['text'],'A search result');self.assertEqual([call[0] for call in calls].count('tools/call'),1)
            altered=dict(results[0]['tool_details'][0],description='stale');loop3=QEventLoop();probe3=RemoteProbe('http://127.0.0.1:'+str(server.server_port)+'/mcp','test-token',invocation={'tool':altered,'arguments':{'query':'MCP'}});stale=[]
            probe3.finished.connect(lambda result:(stale.append(result),loop3.quit()));probe3.start();QTimer.singleShot(5000,loop3.quit);loop3.exec()
            self.assertIn('error',stale[0]);self.assertEqual([call[0] for call in calls].count('tools/call'),1)
            loop4=QEventLoop();probe4=RemoteProbe('http://127.0.0.1:'+str(server.server_port)+'/mcp','test-token',invocation={'tool':results[0]['tool_details'][0],'arguments':{'query':'uncertain'}});uncertain=[]
            probe4.finished.connect(lambda result:(uncertain.append(result),loop4.quit()));probe4.start();QTimer.singleShot(5000,loop4.quit);loop4.exec()
            self.assertTrue(uncertain[0]['call_uncertain']);self.assertEqual([call[0] for call in calls].count('tools/call'),2)
        finally:server.shutdown();server.server_close();thread.join(2)

    def test_remote_discovery_rejects_repeated_cursor(self):
        import threading
        from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
        os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
        from PySide6.QtCore import QEventLoop,QTimer
        from PySide6.QtWidgets import QApplication
        from agentnik.mcp_remote import RemoteProbe
        calls=[]
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def do_POST(self):
                body=json.loads(self.rfile.read(int(self.headers['Content-Length'])));calls.append(body['method'])
                if body['method']=='notifications/initialized':self.send_response(202);self.end_headers();return
                result={'protocolVersion':PROTOCOL,'serverInfo':{'name':'Fake','version':'1'},'capabilities':{'tools':{}}} if body['method']=='initialize' else {'tools':[],'nextCursor':'repeat'}
                payload=json.dumps({'jsonrpc':'2.0','id':body['id'],'result':result}).encode();self.send_response(200);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(payload)));self.end_headers();self.wfile.write(payload)
        app=QApplication.instance() or QApplication([]);server=ThreadingHTTPServer(('127.0.0.1',0),Handler);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        try:
            loop=QEventLoop();probe=RemoteProbe('http://127.0.0.1:'+str(server.server_port)+'/mcp','');results=[]
            probe.finished.connect(lambda result:(results.append(result),loop.quit()));probe.start();QTimer.singleShot(5000,loop.quit);loop.exec()
            self.assertIn('error',results[0]);self.assertEqual(calls.count('tools/list'),2)
        finally:server.shutdown();server.server_close();thread.join(2)

    def test_explicit_local_initialization_and_no_launch_on_open(self):
        os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
        from PySide6.QtCore import QEventLoop,QTimer
        from PySide6.QtWidgets import QApplication,QMessageBox,QDialog
        from agentnik.mcp_ui import MCPServers
        from agentnik.ui import Window
        from agentnik import core
        app=QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as folder,patch.object(core,'discover',return_value={}),patch.object(core,'environment_connections',return_value={}):
            root=Path(folder);marker=root/'started';server=root/'server.py'
            server.write_text('''import json,sys,pathlib
pathlib.Path(sys.argv[1]).write_text("started")
for line in sys.stdin:
 request=json.loads(line); method=request['method']
 if method=='notifications/initialized': continue
 if method=='initialize': result={'protocolVersion':request['params']['protocolVersion'],'serverInfo':{'name':'Fake','version':'1'},'capabilities':{'tools':{}}}
 elif method=='tools/list': result={'tools':[{'name':'query','description':'Run a query','inputSchema':{'type':'object'}}]}
 else: result={'content':[{'type':'text','text':'success'}]}
 print(json.dumps({'jsonrpc':'2.0','id':request['id'],'result':result}),flush=True)
''',encoding='utf-8')
            store=Store(root/'data');store.config['mcp_servers']=[{'name':'Fake','command':sys.executable,'args':[str(server),str(marker)],'enabled':True}];store.flush();window=Window(store)
            try:
                dialog=MCPServers(window);dialog.list.setCurrentRow(0);self.assertFalse(marker.exists())
                with patch.object(QMessageBox,'question',return_value=QMessageBox.StandardButton.Yes):dialog.test()
                loop=QEventLoop();timer=QTimer();timer.timeout.connect(lambda:loop.quit() if dialog.discovered else None);timer.start(10);QTimer.singleShot(5000,loop.quit);loop.exec();timer.stop()
                self.assertIsNotNone(dialog.process);self.assertTrue(marker.exists());self.assertIn('Connected: Fake',dialog.status.text());self.assertEqual(dialog.tool_choice.currentText(),'query')
                session=dialog.process;results=[];session.called.connect(lambda result:results.append(result))
                for _ in range(2):
                    self.assertTrue(session.call(dialog.discovered['tools'][0],{}));loop=QEventLoop();timer=QTimer();timer.timeout.connect(lambda:loop.quit() if len(results)>_ else None);timer.start(10);QTimer.singleShot(5000,loop.quit);loop.exec();timer.stop()
                self.assertEqual(len(results),2);self.assertEqual(results[1]['call_result']['content'][0]['text'],'success')
                with patch.object(QDialog,'exec',return_value=QDialog.DialogCode.Accepted):
                    dialog.call_remote();loop=QEventLoop();timer=QTimer();timer.timeout.connect(lambda:loop.quit() if len(results)>2 else None);timer.start(10);QTimer.singleShot(5000,loop.quit);loop.exec();timer.stop()
                self.assertEqual(len(results),3);self.assertIn('success',dialog.tool_result.toPlainText());dialog.close()
            finally:window.close();app.processEvents();store.db.close()

    def test_resource_template_expansion_and_pagination(self):
        from agentnik.mcp_resources import TemplatePages,expand_template
        self.assertEqual(expand_template('test://item/{id}',{'id':'a/b ?'}),'test://item/a%2Fb%20%3F')
        for template,values in [('test://x/{+id}',{'id':'a'}),('test://x/{id}',{}),('test://x/{id}',{'id':['bad']}),('test://x/{id',{'id':'a'})]:
            with self.subTest(template=template),self.assertRaises(ValueError):expand_template(template,values)
        pages=TemplatePages();cursor,result=pages.accept({'resourceTemplates':[{'uriTemplate':'test://x/{id}','name':'One'},{'uriTemplate':'test://x/{+id}','name':'Complex'}],'nextCursor':'next'})
        self.assertEqual(cursor,'next');self.assertTrue(result['templates'][0]['supported']);self.assertFalse(result['templates'][1]['supported'])
        with self.assertRaises(ValueError):pages.accept({'resourceTemplates':[],'nextCursor':'next'})

    def test_local_resource_template_listing_and_read(self):
        os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
        from PySide6.QtCore import QEventLoop,QTimer
        from PySide6.QtWidgets import QApplication
        from agentnik.mcp_local import LocalSession
        app=QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as folder:
            server=Path(folder)/'templates.py'
            server.write_text('''import json,sys
for line in sys.stdin:
 req=json.loads(line);method=req['method']
 if method=='notifications/initialized':continue
 if method=='initialize':result={'protocolVersion':req['params']['protocolVersion'],'serverInfo':{'name':'Fake','version':'1'},'capabilities':{'resources':{}}}
 elif method=='resources/templates/list':result={'resourceTemplates':[{'uriTemplate':'test://item/{id}','name':'Item'}]}
 elif method=='resources/read':result={'contents':[{'uri':req['params']['uri'],'text':'content'}]}
 else:raise RuntimeError('unexpected')
 print(json.dumps({'jsonrpc':'2.0','id':req['id'],'result':result}),flush=True)
''',encoding='utf-8')
            session=LocalSession(sys.executable,[str(server)]);loop=QEventLoop();out=[]
            def received(result):
                out.append(result)
                if len(out)==1:
                    template=result['templates'][0];self.assertFalse(session.read_resource_template(template,{'id':'a/b'},'test://item/a/b'));self.assertTrue(session.read_resource_template(template,{'id':'a/b'},'test://item/a%2Fb'))
                else:loop.quit()
            session.discovered.connect(lambda _:session.list_resource_templates());session.resources.connect(received);session.ended.connect(lambda result:(out.append(result),loop.quit()));session.start();QTimer.singleShot(5000,loop.quit);loop.exec();session.close()
            self.assertEqual(out[1]['contents'][0]['uri'],'test://item/a%2Fb');self.assertEqual(out[1]['contents'][0]['text'],'content')

    def test_resource_pagination_limits_and_invalid_cursors(self):
        from agentnik.mcp_resources import ResourcePages
        pages=ResourcePages()
        for i in range(5):
            cursor,out=pages.accept({'resources':[{'uri':'test://'+str(i),'name':str(i)}],'nextCursor':'cursor-'+str(i)})
            self.assertEqual(cursor,'cursor-'+str(i) if i<4 else None)
        self.assertTrue(out['more_resources']);self.assertEqual(len(out['resources']),5)
        pages=ResourcePages();pages.accept({'resources':[],'nextCursor':'same'})
        with self.assertRaisesRegex(ValueError,'Repeated'):pages.accept({'resources':[],'nextCursor':'same'})
        pages=ResourcePages();pages.accept({'resources':[{'uri':'test://a','name':'a'}],'nextCursor':'next'})
        with self.assertRaisesRegex(ValueError,'Duplicate'):pages.accept({'resources':[{'uri':'test://a','name':'a'}]})
        pages=ResourcePages();cursor,out=pages.accept({'resources':[{'uri':'test://'+str(i),'name':str(i)} for i in range(100)],'nextCursor':'more'})
        self.assertIsNone(cursor);self.assertTrue(out['more_resources']);self.assertEqual(len(out['resources']),100)
        pages=ResourcePages();cursor,out=pages.accept({'resources':[{'uri':'test://'+str(i),'name':str(i),'description':'x'*4000} for i in range(60)]})
        self.assertIsNone(cursor);self.assertTrue(out['more_resources']);self.assertLess(len(out['resources']),60)

    def test_prompt_validation_and_pagination(self):
        from agentnik.mcp_prompts import PromptPages,validate_prompt_arguments,parse_prompt_messages
        pages=PromptPages();cursor,result=pages.accept({'prompts':[{'name':'review','description':'Review','arguments':[{'name':'code','required':True}]}],'nextCursor':'next'})
        self.assertEqual(cursor,'next');prompt=result['prompts'][0];self.assertTrue(validate_prompt_arguments(prompt,{'code':'hello'}))
        for args in ({},{'code':1},{'code':'x','extra':'y'}):
            with self.assertRaises(ValueError):validate_prompt_arguments(prompt,args)
        with self.assertRaises(ValueError):pages.accept({'prompts':[],'nextCursor':'next'})
        with self.assertRaises(ValueError):parse_prompt_messages({'messages':[{'role':'system','content':{'type':'text','text':'bad'}}]})
        with self.assertRaises(ValueError):parse_prompt_messages({'messages':[{'role':'user','content':{'type':'image','data':'a'}}]})

    def test_local_prompt_listing_get_and_definition_recheck(self):
        os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
        from PySide6.QtCore import QEventLoop,QTimer
        from PySide6.QtWidgets import QApplication
        from agentnik.mcp_local import LocalSession
        app=QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as folder:
            server=Path(folder)/'prompt_server.py';marker=Path(folder)/'called'
            server.write_text('''import json,sys,pathlib
pages=0
for line in sys.stdin:
 req=json.loads(line);method=req['method']
 if method=='notifications/initialized':continue
 if method=='initialize':result={'protocolVersion':req['params']['protocolVersion'],'serverInfo':{'name':'Fake','version':'1'},'capabilities':{'prompts':{}}}
 elif method=='prompts/list':
  pages+=1;result={'prompts':[{'name':'review','description':'Changed' if pages>2 else 'Review','arguments':[{'name':'code','required':True}]}]}
 elif method=='prompts/get':
  pathlib.Path(sys.argv[1]).write_text('called');result={'messages':[{'role':'user','content':{'type':'text','text':'Review '+req['params']['arguments']['code']}}]}
 else:raise RuntimeError('unexpected')
 print(json.dumps({'jsonrpc':'2.0','id':req['id'],'result':result}),flush=True)
''',encoding='utf-8')
            session=LocalSession(sys.executable,[str(server),str(marker)]);loop=QEventLoop();out=[]
            def response(result):
                out.append(result)
                if len(out)==1:
                    prompt=result['prompts'][0];self.assertFalse(session.list_prompts({'prompt':prompt,'arguments':{}}));self.assertTrue(session.list_prompts({'prompt':prompt,'arguments':{'code':'safe'}}))
                elif len(out)==2:
                    self.assertTrue(marker.exists());marker.unlink();self.assertTrue(session.list_prompts({'prompt':out[0]['prompts'][0],'arguments':{'code':'safe'}}))
            session.discovered.connect(lambda _:session.list_prompts());session.prompts.connect(response);session.ended.connect(lambda result:(out.append(result),loop.quit()));session.start();QTimer.singleShot(5000,loop.quit);loop.exec();session.close()
            self.assertEqual(out[1]['messages'][0]['content']['text'],'Review safe');self.assertIn('definition changed',out[2]['error']);self.assertFalse(marker.exists())

    def test_local_resource_listing_and_text_read(self):
        os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
        from PySide6.QtCore import QEventLoop,QTimer
        from PySide6.QtWidgets import QApplication
        from agentnik.mcp_local import LocalSession
        app=QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as folder:
            server=Path(folder)/'resources.py'
            server.write_text('''import json,sys
for line in sys.stdin:
 req=json.loads(line);method=req['method']
 if method=='notifications/initialized':continue
 if method=='initialize':result={'protocolVersion':req['params']['protocolVersion'],'serverInfo':{'name':'Fake','version':'1'},'capabilities':{'resources':{}}}
 elif method=='resources/list':result={'resources':[{'uri':'test://record/2','name':'Second'}]} if req.get('params',{}).get('cursor') else {'resources':[{'uri':'test://record/1','name':'Record','description':'Test','mimeType':'text/plain'}],'nextCursor':'next'}
 elif method=='resources/read':result={'contents':[{'uri':req['params']['uri'],'text':'Resource text','mimeType':'text/plain'}]}
 else:raise RuntimeError('unexpected')
 print(json.dumps({'jsonrpc':'2.0','id':req['id'],'result':result}),flush=True)
''',encoding='utf-8')
            session=LocalSession(sys.executable,[str(server)]);loop=QEventLoop();results=[]
            def ready(info):
                self.assertIn('resources',info['capabilities']);self.assertTrue(session.list_resources())
            def resource(result):
                results.append(result)
                if len(results)==1:
                    self.assertFalse(session.read_resource('test://unlisted'));self.assertTrue(session.read_resource(result['resources'][1]['uri']))
                else:loop.quit()
            session.discovered.connect(ready);session.resources.connect(resource);session.ended.connect(lambda result:(results.append(result),loop.quit()));session.start();QTimer.singleShot(5000,loop.quit);loop.exec();session.close()
            self.assertEqual(results[0]['resources'][0]['name'],'Record');self.assertFalse(results[0]['more_resources']);self.assertEqual(results[0]['resources'][1]['name'],'Second');self.assertEqual(results[1]['contents'][0]['text'],'Resource text')

    def test_local_resource_read_rejects_binary_and_mismatched_uri(self):
        os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
        from PySide6.QtCore import QEventLoop,QTimer
        from PySide6.QtWidgets import QApplication
        from agentnik.mcp_local import LocalSession
        app=QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as folder:
            server=Path(folder)/'bad_resources.py'
            server.write_text('''import json,sys
for line in sys.stdin:
 req=json.loads(line);method=req['method']
 if method=='notifications/initialized':continue
 if method=='initialize':result={'protocolVersion':req['params']['protocolVersion'],'serverInfo':{'name':'Fake','version':'1'},'capabilities':{'resources':{}}}
 elif method=='resources/list':result={'resources':[{'uri':'test://one','name':'One'}]}
 else:result={'contents':[{'uri':'test://other','text':'unexpected'}] if sys.argv[1]=='mismatch' else [{'uri':'test://one','blob':'YWJj'}]}
 print(json.dumps({'jsonrpc':'2.0','id':req['id'],'result':result}),flush=True)
''',encoding='utf-8')
            for mode in ('mismatch','binary'):
                with self.subTest(mode=mode):
                    session=LocalSession(sys.executable,[str(server),mode]);loop=QEventLoop();out=[]
                    session.discovered.connect(lambda _:session.list_resources())
                    session.resources.connect(lambda result:session.read_resource(result['resources'][0]['uri']))
                    session.ended.connect(lambda result:(out.append(result),loop.quit()))
                    session.start();QTimer.singleShot(5000,loop.quit);loop.exec();session.close()
                    self.assertIn('Invalid or unsupported',out[0]['error'])

    def test_local_call_rechecks_definition_before_execution(self):
        os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
        from PySide6.QtCore import QEventLoop,QTimer
        from PySide6.QtWidgets import QApplication
        from agentnik.mcp_local import LocalSession
        app=QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as folder:
            server=Path(folder)/'server.py';marker=Path(folder)/'called'
            server.write_text('''import json,sys,pathlib
pages=0
for line in sys.stdin:
 request=json.loads(line);method=request['method']
 if method=='notifications/initialized':continue
 if method=='initialize':result={'protocolVersion':request['params']['protocolVersion'],'serverInfo':{'name':'Fake','version':'1'},'capabilities':{'tools':{}}}
 elif method=='tools/list':
  pages+=1;result={'tools':[{'name':'query','description':'Original' if pages==1 else 'Changed','inputSchema':{'type':'object'}}]}
 else:
  pathlib.Path(sys.argv[1]).write_text('called');result={'content':[]}
 print(json.dumps({'jsonrpc':'2.0','id':request['id'],'result':result}),flush=True)
''',encoding='utf-8')
            session=LocalSession(sys.executable,[str(server),str(marker)]);loop=QEventLoop();out=[]
            session.discovered.connect(lambda info:session.call(info['tool_details'][0],{}))
            session.ended.connect(lambda result:(out.append(result),loop.quit()))
            session.start();QTimer.singleShot(5000,loop.quit);loop.exec();session.close()
            self.assertIn('definition changed',out[0]['error']);self.assertFalse(out[0]['call_uncertain']);self.assertFalse(marker.exists())

    def test_remote_prompt_session_and_secret_isolation(self):
        import threading
        from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
        os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
        from PySide6.QtCore import QEventLoop,QTimer
        from PySide6.QtWidgets import QApplication
        from agentnik.mcp_code import CodingMCPBridge
        from agentnik.tools import Runtime,Limits
        calls=[]
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def do_POST(self):
                body=json.loads(self.rfile.read(int(self.headers['Content-Length'])));method=body['method'];calls.append((method,self.headers.get('Mcp-Session-Id')))
                if method=='notifications/initialized':self.send_response(202);self.end_headers();return
                if method=='initialize':result={'protocolVersion':PROTOCOL,'serverInfo':{'name':'Fake','version':'1'},'capabilities':{'prompts':{}}}
                elif method=='prompts/list':result={'prompts':[{'name':'review','arguments':[{'name':'code','required':True}]}]}
                elif method=='prompts/get':result={'messages':[{'role':'user','content':{'type':'text','text':'Review '+body['params']['arguments']['code']}}]}
                else:raise AssertionError(method)
                payload=json.dumps({'jsonrpc':'2.0','id':body['id'],'result':result}).encode();self.send_response(200);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(payload)));self.send_header('Mcp-Session-Id','session-one');self.end_headers();self.wfile.write(payload)
            def do_DELETE(self):calls.append(('DELETE',self.headers.get('Mcp-Session-Id')));self.send_response(204);self.end_headers()
        app=QApplication.instance() or QApplication([]);server=ThreadingHTTPServer(('127.0.0.1',0),Handler);server_thread=threading.Thread(target=server.serve_forever,daemon=True);server_thread.start()
        config={'mcp_servers':[{'name':'Remote','transport':'http','url':'http://127.0.0.1:'+str(server.server_port)+'/mcp','credential_id':'id','enabled':True}]};bridge=CodingMCPBridge(config['mcp_servers'][0],config);runtime=Runtime(threading.Event(),Limits());out=[]
        def work():
            out.append(bridge.request('discover',{},runtime));out.append(bridge.request('prompts_list',{},runtime));prompt=out[1]['prompts'][0]
            out.append(bridge.request('prompts_get',{'prompt':prompt,'arguments':{'code':'secret-token'}},runtime));out.append(bridge.request('prompts_get',{'prompt':prompt,'arguments':{'code':'safe'}},runtime));bridge.close_signal.emit()
        try:
            with patch('keyring.get_password',return_value='secret-token'):
                thread=threading.Thread(target=work);thread.start();loop=QEventLoop();timer=QTimer();timer.timeout.connect(lambda:loop.quit() if not thread.is_alive() and any(c[0]=='DELETE' for c in calls) else None);timer.start(10);QTimer.singleShot(5000,loop.quit);loop.exec();timer.stop();thread.join(1)
            self.assertFalse(thread.is_alive());self.assertIn('error',out[2]);self.assertEqual(out[3]['messages'][0]['content']['text'],'Review safe');self.assertEqual([c[0] for c in calls].count('prompts/get'),1);self.assertTrue(all(c[1]=='session-one' for c in calls[1:]));self.assertNotIn('secret-token',str(out))
        finally:bridge.close();server.shutdown();server.server_close();server_thread.join(2)

    def test_remote_resource_listing_and_read_in_authenticated_session(self):
        import threading
        from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
        os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
        from PySide6.QtCore import QEventLoop,QTimer
        from PySide6.QtWidgets import QApplication
        from agentnik.mcp_code import CodingMCPBridge
        from agentnik.tools import Runtime,Limits
        calls=[]
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def do_POST(self):
                body=json.loads(self.rfile.read(int(self.headers['Content-Length'])));method=body['method'];calls.append((method,self.headers.get('Mcp-Session-Id'),self.headers.get('Authorization')))
                if method=='notifications/initialized':self.send_response(202);self.end_headers();return
                if method=='initialize':result={'protocolVersion':PROTOCOL,'serverInfo':{'name':'Fake','version':'1'},'capabilities':{'resources':{}}}
                elif method=='resources/list':result={'resources':[{'uri':'test://two','name':'Two'}]} if body.get('params',{}).get('cursor') else {'resources':[{'uri':'test://one','name':'One','description':'Example'}],'nextCursor':'next'}
                elif method=='resources/read':result={'contents':[{'uri':body['params']['uri'],'text':'Evidence'}]}
                else:raise AssertionError(method)
                payload=json.dumps({'jsonrpc':'2.0','id':body['id'],'result':result}).encode();self.send_response(200);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(payload)));self.send_header('Mcp-Session-Id','session-one');self.end_headers();self.wfile.write(payload)
            def do_DELETE(self):
                calls.append(('DELETE',self.headers.get('Mcp-Session-Id'),self.headers.get('Authorization')));self.send_response(204);self.end_headers()
        app=QApplication.instance() or QApplication([]);server=ThreadingHTTPServer(('127.0.0.1',0),Handler);server_thread=threading.Thread(target=server.serve_forever,daemon=True);server_thread.start()
        config={'mcp_servers':[{'name':'Remote','transport':'http','url':'http://127.0.0.1:'+str(server.server_port)+'/mcp','credential_id':'id','enabled':True}]};bridge=CodingMCPBridge(config['mcp_servers'][0],config);runtime=Runtime(threading.Event(),Limits());out=[]
        def work():
            out.append(bridge.request('discover',{},runtime));out.append(bridge.request('resources_list',{},runtime))
            out.append(bridge.request('resources_read',{'uri':'test://unlisted'},runtime));out.append(bridge.request('resources_read',{'uri':'test://two'},runtime));bridge.close_signal.emit()
        try:
            with patch('keyring.get_password',return_value='secret-token'):
                thread=threading.Thread(target=work);thread.start();loop=QEventLoop();timer=QTimer();timer.timeout.connect(lambda:loop.quit() if not thread.is_alive() and any(c[0]=='DELETE' for c in calls) else None);timer.start(10);QTimer.singleShot(5000,loop.quit);loop.exec();timer.stop();thread.join(1)
            self.assertFalse(thread.is_alive());self.assertIn('resources',out[0]['capabilities']);self.assertFalse(out[1]['more_resources']);self.assertEqual(len(out[1]['resources']),2);self.assertIn('error',out[2]);self.assertEqual(out[3]['contents'][0]['text'],'Evidence')
            self.assertEqual([c[0] for c in calls],['initialize','notifications/initialized','resources/list','resources/list','resources/read','DELETE']);self.assertTrue(all(c[1]=='session-one' for c in calls[1:]));self.assertTrue(all(c[2]=='Bearer secret-token' for c in calls));self.assertNotIn('secret-token',str(out))
        finally:bridge.close();server.shutdown();server.server_close();server_thread.join(2)

    def test_coding_remote_session_is_stateful_and_rechecks_tool_changes(self):
        import threading
        from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
        os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
        from PySide6.QtCore import QEventLoop,QTimer
        from PySide6.QtWidgets import QApplication
        from agentnik.mcp_code import CodingMCPBridge
        from agentnik.tools import Runtime,Limits
        calls=[];state={'value':0,'changed':False}
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def do_POST(self):
                body=json.loads(self.rfile.read(int(self.headers['Content-Length'])));method=body['method'];calls.append((method,body.get('id'),self.headers.get('Mcp-Session-Id')))
                if method=='notifications/initialized':self.send_response(202);self.end_headers();return
                if method=='initialize':result={'protocolVersion':PROTOCOL,'serverInfo':{'name':'Fake','version':'1'},'capabilities':{'tools':{}}}
                elif method=='tools/list':result={'tools':[{'name':'step','description':'Changed' if state['changed'] else 'Count','inputSchema':{'type':'object'}}]}
                else:state['value']+=1;result={'content':[{'type':'text','text':str(state['value'])}]}
                payload=json.dumps({'jsonrpc':'2.0','id':body['id'],'result':result}).encode();self.send_response(200);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(payload)));self.send_header('Mcp-Session-Id','session-one');self.end_headers();self.wfile.write(payload)
            def do_DELETE(self):
                calls.append(('DELETE',None,self.headers.get('Mcp-Session-Id')));self.send_response(204);self.end_headers()
        app=QApplication.instance() or QApplication([]);server=ThreadingHTTPServer(('127.0.0.1',0),Handler);server_thread=threading.Thread(target=server.serve_forever,daemon=True);server_thread.start()
        config={'mcp_servers':[{'name':'Remote','transport':'http','url':'http://127.0.0.1:'+str(server.server_port)+'/mcp','credential_id':'','enabled':True}]};bridge=CodingMCPBridge(config['mcp_servers'][0],config);runtime=Runtime(threading.Event(),Limits());out=[]
        def work():
            info=bridge.request('discover',{},runtime);payload={'tool':info['tool_details'][0],'arguments':{}}
            out.append(bridge.request('call',payload,runtime));out.append(bridge.request('call',payload,runtime));state['changed']=True
            out.append(bridge.request('call',payload,runtime));bridge.close_signal.emit()
        try:
            thread=threading.Thread(target=work);thread.start();loop=QEventLoop();timer=QTimer();timer.timeout.connect(lambda:loop.quit() if not thread.is_alive() and any(item[0]=='DELETE' for item in calls) else None);timer.start(10);QTimer.singleShot(5000,loop.quit);loop.exec();timer.stop();thread.join(1)
            self.assertFalse(thread.is_alive());self.assertEqual([out[0]['call_result']['content'][0]['text'],out[1]['call_result']['content'][0]['text']],['1','2'])
            self.assertIn('definition changed',out[2]['error']);self.assertEqual([c[0] for c in calls].count('initialize'),1);self.assertEqual([c[0] for c in calls].count('tools/call'),2)
            self.assertTrue(all(c[2]=='session-one' for c in calls[1:]));ids=[c[1] for c in calls if c[1] is not None];self.assertEqual(len(ids),len(set(ids)));self.assertEqual(calls[-1][0],'DELETE')
        finally:bridge.close();server.shutdown();server.server_close();server_thread.join(2)

    def test_coding_remote_bridge_rechecks_and_stops_after_uncertainty(self):
        import threading
        from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
        os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
        from PySide6.QtCore import QEventLoop,QTimer
        from PySide6.QtWidgets import QApplication
        from agentnik.mcp_code import CodingMCPBridge
        from agentnik.tools import Runtime,Limits
        calls=[]
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def do_POST(self):
                body=json.loads(self.rfile.read(int(self.headers['Content-Length'])));method=body['method'];calls.append(method)
                if method=='notifications/initialized':self.send_response(202);self.end_headers();return
                if method=='tools/call':self.connection.close();return
                result={'protocolVersion':PROTOCOL,'serverInfo':{'name':'Fake','version':'1'},'capabilities':{'tools':{}}} if method=='initialize' else {'tools':[{'name':'query','description':'Query','inputSchema':{'type':'object'}}]}
                payload=json.dumps({'jsonrpc':'2.0','id':body['id'],'result':result}).encode();self.send_response(200);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(payload)));self.end_headers();self.wfile.write(payload)
        app=QApplication.instance() or QApplication([]);server=ThreadingHTTPServer(('127.0.0.1',0),Handler);server_thread=threading.Thread(target=server.serve_forever,daemon=True);server_thread.start()
        config={'mcp_servers':[{'name':'Remote','transport':'http','url':'http://127.0.0.1:'+str(server.server_port)+'/mcp','credential_id':'saved','enabled':True}]};bridge=CodingMCPBridge(config['mcp_servers'][0],config);runtime=Runtime(threading.Event(),Limits());out=[]
        def work():
            info=bridge.request('discover',{},runtime);out.append(info);payload={'tool':info['tool_details'][0],'arguments':{}}
            out.append(bridge.request('call',payload,runtime));out.append(bridge.request('call',payload,runtime));bridge.close_signal.emit()
        try:
            with patch('keyring.get_password',return_value='secret-token'):
                thread=threading.Thread(target=work);thread.start();loop=QEventLoop();timer=QTimer();timer.timeout.connect(lambda:loop.quit() if not thread.is_alive() else None);timer.start(10);QTimer.singleShot(5000,loop.quit);loop.exec();timer.stop();thread.join(1);app.processEvents()
            self.assertFalse(thread.is_alive());self.assertTrue(out[1]['call_uncertain']);self.assertIn('uncertain',out[2]['error']);self.assertEqual(calls.count('tools/call'),1);self.assertNotIn('secret-token',str(out))
        finally:bridge.close();server.shutdown();server.server_close();server_thread.join(2)

    def test_remote_response_secret_is_detected_after_json_unescaping(self):
        from agentnik.mcp_remote import contains_secret
        self.assertTrue(contains_secret(json.loads('{"text":"s\\u0065cret"}'),'secret'))
        self.assertTrue(contains_secret({'secret':'value'},'secret'))

    def test_coding_bridge_keeps_local_session_and_checks_configuration(self):
        import threading
        os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
        from PySide6.QtCore import QEventLoop,QTimer
        from PySide6.QtWidgets import QApplication
        from agentnik.mcp_code import CodingMCPBridge
        from agentnik.tools import Runtime,Limits
        app=QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as folder,patch.dict(os.environ,{'AGENTNIK_MCP_TEST_SOURCE':'snapshot-unique-value'}):
            server=Path(folder)/'server.py'
            server.write_text('''import json,os,sys
for line in sys.stdin:
 request=json.loads(line);method=request['method']
 if method=='notifications/initialized':continue
 if method=='initialize':result={'protocolVersion':request['params']['protocolVersion'],'serverInfo':{'name':'Fake' if os.environ.get('TARGET_TOKEN')=='snapshot-unique-value' else 'Incorrect','version':'1'},'capabilities':{'tools':{}}}
 elif method=='tools/list':result={'tools':[{'name':'query','inputSchema':{'type':'object'}}]}
 else:result={'content':[{'type':'text','text':'ok'}]}
 print(json.dumps({'jsonrpc':'2.0','id':request['id'],'result':result}),flush=True)
''',encoding='utf-8')
            config={'mcp_servers':[{'name':'Fake','command':sys.executable,'args':[str(server)],'env':{'TARGET_TOKEN':'AGENTNIK_MCP_TEST_SOURCE'},'enabled':True}]};bridge=CodingMCPBridge(config['mcp_servers'][0],config)
            os.environ['AGENTNIK_MCP_TEST_SOURCE']='changed-after-snapshot'
            runtime=Runtime(threading.Event(),Limits());out=[]
            def work():
                info=bridge.request('discover',{},runtime);out.append(info)
                out.append(bridge.request('call',{'tool':info['tool_details'][0],'arguments':{}},runtime))
                config['mcp_servers']=[]
                out.append(bridge.request('call',{'tool':info['tool_details'][0],'arguments':{}},runtime));bridge.close_signal.emit()
            thread=threading.Thread(target=work);thread.start();loop=QEventLoop();timer=QTimer();timer.timeout.connect(lambda:loop.quit() if not thread.is_alive() else None);timer.start(10);QTimer.singleShot(5000,loop.quit);loop.exec();timer.stop();thread.join(1);app.processEvents()
            self.assertFalse(thread.is_alive());self.assertEqual(out[1]['call_result']['content'][0]['text'],'ok');self.assertIn('changed',out[2]['error']);self.assertTrue(bridge.closed)

    def test_local_environment_mapping_editor_saves_and_reloads(self):
        os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
        from PySide6.QtWidgets import QApplication,QMessageBox
        from agentnik.mcp_ui import MCPServers
        from agentnik.ui import Window
        from agentnik import core
        app=QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as folder,patch.object(core,'discover',return_value={}),patch.object(core,'environment_connections',return_value={}),patch.dict(os.environ,{'AGENTNIK_TEST_MCP_TOKEN':'secret-mapped-value'}):
            store=Store(folder);window=Window(store)
            try:
                dialog=MCPServers(window);dialog.name.setText('Local');dialog.command.setText(sys.executable);dialog.args.setPlainText('[]');dialog.env.setPlainText('{"SERVER_TOKEN":"AGENTNIK_TEST_MCP_TOKEN"}');dialog.save()
                self.assertEqual(store.config['mcp_servers'][0]['env'],{'SERVER_TOKEN':'AGENTNIK_TEST_MCP_TOKEN'});self.assertNotIn('secret-mapped-value',store.config_path.read_text(encoding='utf-8'))
                self.assertEqual(json.loads(dialog.env.toPlainText()),{'SERVER_TOKEN':'AGENTNIK_TEST_MCP_TOKEN'})
                dialog.env.setPlainText('{"bad=name":"SOURCE"}')
                with patch.object(QMessageBox,'warning') as warning:dialog.save();warning.assert_called_once()
                self.assertEqual(store.config['mcp_servers'][0]['env'],{'SERVER_TOKEN':'AGENTNIK_TEST_MCP_TOKEN'});dialog.close()
            finally:window.close();app.processEvents();store.db.close()

    def test_remote_credential_uses_keyring_and_is_not_reused_for_changed_url(self):
        os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
        from PySide6.QtWidgets import QApplication,QDialog
        from PySide6.QtCore import QEventLoop,QTimer
        from agentnik.mcp_ui import MCPServers
        from agentnik.ui import Window
        from agentnik import core
        app=QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as folder,patch.object(core,'discover',return_value={}),patch.object(core,'environment_connections',return_value={}):
            store=Store(folder);window=Window(store)
            try:
                dialog=MCPServers(window);dialog.transport.setCurrentIndex(1);dialog.name.setText('Remote');dialog.url.setText('https://example.com/mcp');dialog.token.setText('secret-test-token')
                with patch('keyring.set_password') as put,patch('keyring.delete_password') as delete:
                    dialog.save();put.assert_called_once();self.assertNotIn('secret-test-token',store.config_path.read_text(encoding='utf-8'))
                    self.assertTrue(store.config['mcp_servers'][0]['credential_id']);dialog.url.setText('https://other.example/mcp');dialog.save()
                    self.assertEqual(store.config['mcp_servers'][0]['credential_id'],'');delete.assert_called_once()
                dialog.discovered_config=dict(store.config['mcp_servers'][0]);dialog.remote_done({'name':'Fake','version':'1','protocol':PROTOCOL,'tools':['search'],'tool_details':[{'name':'search','description':'Search web','description_clipped':False,'schema':{'type':'object'},'schema_status':'available'}]})
                self.assertIn('Search web',dialog.tool_details.toPlainText());self.assertIn('"type": "object"',dialog.tool_details.toPlainText())
                def wait_validation():
                    loop=QEventLoop();timer=QTimer();timer.timeout.connect(lambda:loop.quit() if dialog.validation_job is None else None);timer.start(10);QTimer.singleShot(5000,loop.quit);loop.exec();timer.stop();self.assertIsNone(dialog.validation_job)
                dialog.tool_args.setPlainText('{"value":1e999}');dialog.call_remote();self.assertIsNone(dialog.validation_job);self.assertIn('JSON object',dialog.status.text());dialog.tool_args.setPlainText('{}')
                dialog.discovered['tools'][0]['schema']={'type':'object','required':['query']}
                with patch.object(QDialog,'exec') as review:
                    dialog.call_remote();wait_validation();review.assert_not_called();self.assertIn('do not match',dialog.status.text())
                dialog.discovered['tools'][0]['schema']={'type':'object'}
                with patch.object(QDialog,'exec',return_value=QDialog.DialogCode.Rejected) as review:
                    dialog.call_remote();wait_validation();review.assert_called_once()
                self.assertIsNone(dialog.remote)
                dialog.tool_args.setPlainText('{"query":"MCP"}')
                with patch.object(QDialog,'exec',return_value=QDialog.DialogCode.Accepted),patch('agentnik.mcp_remote.RemoteProbe') as remote:
                    dialog.call_remote();wait_validation();remote.assert_called_once()
                    self.assertEqual(remote.call_args.kwargs['invocation']['arguments'],{'query':'MCP'});remote.return_value.start.assert_called_once()
                    dialog.remote=None
                dialog.close()
            finally:window.close();app.processEvents();store.db.close()
