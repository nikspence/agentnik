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
        for unsafe in ({'type':'object','$ref':'https://example.com/schema'},{'type':'object','properties':{'q':{'type':'string','pattern':'(a+)+$'}}},{'type':'object','allOf':[]}):
            with self.subTest(schema=unsafe),self.assertRaisesRegex(ValueError,'unsupported'):validate_tool_arguments(unsafe,{})
        with self.assertRaisesRegex(ValueError,'invalid'):validate_tool_arguments({'type':'object','required':'query'}, {})

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
        app=QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as folder:
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

    def test_coding_bridge_keeps_local_session_and_checks_configuration(self):
        import threading
        os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
        from PySide6.QtCore import QEventLoop,QTimer
        from PySide6.QtWidgets import QApplication
        from agentnik.mcp_code import CodingMCPBridge
        from agentnik.tools import Runtime,Limits
        app=QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as folder:
            server=Path(folder)/'server.py'
            server.write_text('''import json,sys
for line in sys.stdin:
 request=json.loads(line);method=request['method']
 if method=='notifications/initialized':continue
 if method=='initialize':result={'protocolVersion':request['params']['protocolVersion'],'serverInfo':{'name':'Fake','version':'1'},'capabilities':{'tools':{}}}
 elif method=='tools/list':result={'tools':[{'name':'query','inputSchema':{'type':'object'}}]}
 else:result={'content':[{'type':'text','text':'ok'}]}
 print(json.dumps({'jsonrpc':'2.0','id':request['id'],'result':result}),flush=True)
''',encoding='utf-8')
            config={'mcp_servers':[{'name':'Fake','command':sys.executable,'args':[str(server)],'enabled':True}]};bridge=CodingMCPBridge(config['mcp_servers'][0],config)
            runtime=Runtime(threading.Event(),Limits());out=[]
            def work():
                info=bridge.request('discover',{},runtime);out.append(info)
                out.append(bridge.request('call',{'tool':info['tool_details'][0],'arguments':{}},runtime))
                config['mcp_servers']=[]
                out.append(bridge.request('call',{'tool':info['tool_details'][0],'arguments':{}},runtime));bridge.close_signal.emit()
            thread=threading.Thread(target=work);thread.start();loop=QEventLoop();timer=QTimer();timer.timeout.connect(lambda:loop.quit() if not thread.is_alive() else None);timer.start(10);QTimer.singleShot(5000,loop.quit);loop.exec();timer.stop();thread.join(1);app.processEvents()
            self.assertFalse(thread.is_alive());self.assertEqual(out[1]['call_result']['content'][0]['text'],'ok');self.assertIn('changed',out[2]['error']);self.assertTrue(bridge.closed)

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
