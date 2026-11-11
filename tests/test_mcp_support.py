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
        for message in (b'not json',json.dumps(dict(result,id=True)).encode(),json.dumps(dict(result,result={'protocolVersion':'different'})).encode()):
            with self.assertRaises(ValueError):parse_initialize(message)

    def test_remote_validation_and_sse_messages(self):
        from agentnik.mcp_remote import response_message
        remote={'name':'Parallel','transport':'http','url':'https://mcp.parallel.ai/mcp','credential_id':'opaque','enabled':True}
        validate_servers([remote])
        for url in ('http://example.com/mcp','https://user:secret@example.com/mcp','https://example.com/mcp?key=secret'):
            with self.assertRaises(ValueError):validate_servers([dict(remote,url=url)])
        body=b': keepalive\n\ndata: {"jsonrpc":"2.0","id":1,"result":{}}\n\n'
        self.assertEqual(response_message(body,'text/event-stream',1)['id'],1)
        with self.assertRaises(ValueError):response_message(body+body,'text/event-stream',1)
        with self.assertRaises(ValueError):response_message(b'{"jsonrpc":"2.0","id":9}','application/json',1)

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
                if method=='initialize':result={'protocolVersion':PROTOCOL,'serverInfo':{'name':'Fake','version':''},'capabilities':{'tools':{}}}
                elif not body.get('params',{}).get('cursor'):result={'tools':[{'name':'web_search'}],'nextCursor':'page-2'}
                else:result={'tools':[{'name':'web_fetch'}]}
                payload=('data: '+json.dumps({'jsonrpc':'2.0','id':body['id'],'result':result})+'\n\n').encode()
                self.send_response(200);self.send_header('Content-Type','text/event-stream');self.send_header('Content-Length',str(len(payload)));self.send_header('Mcp-Session-Id','session-1');self.end_headers();self.wfile.write(payload)
            def do_DELETE(self):
                calls.append(('DELETE',self.headers.get('Mcp-Session-Id'),self.headers.get('MCP-Protocol-Version'),self.headers.get('Authorization')));self.send_response(204);self.end_headers()
        app=QApplication.instance() or QApplication([]);server=ThreadingHTTPServer(('127.0.0.1',0),Handler);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        try:
            loop=QEventLoop();probe=RemoteProbe('http://127.0.0.1:'+str(server.server_port)+'/mcp','test-token');results=[]
            probe.finished.connect(lambda result:(results.append(result),loop.quit()));probe.start();QTimer.singleShot(5000,loop.quit);loop.exec()
            self.assertEqual(results[0]['tools'],['web_search','web_fetch']);self.assertEqual(results[0]['version'],'unknown');self.assertTrue(results[0]['session_closed'])
            self.assertEqual([call[0] for call in calls],['initialize','notifications/initialized','tools/list','tools/list','DELETE'])
            self.assertTrue(all(call[1:3]==('session-1',PROTOCOL) for call in calls[1:]));self.assertTrue(all(call[3]=='Bearer test-token' for call in calls))
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
        from PySide6.QtWidgets import QApplication,QMessageBox
        from agentnik.mcp_ui import MCPServers
        from agentnik.ui import Window
        app=QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);marker=root/'started';server=root/'server.py'
            server.write_text('import json,sys,pathlib\npathlib.Path(sys.argv[1]).write_text("started")\nrequest=json.loads(sys.stdin.readline())\nprint(json.dumps({"jsonrpc":"2.0","id":request["id"],"result":{"protocolVersion":request["params"]["protocolVersion"],"serverInfo":{"name":"Fake","version":"1"},"capabilities":{"tools":{}}}}),flush=True)\n',encoding='utf-8')
            store=Store(root/'data');store.config['mcp_servers']=[{'name':'Fake','command':sys.executable,'args':[str(server),str(marker)],'enabled':True}];store.flush();window=Window(store)
            try:
                dialog=MCPServers(window);dialog.list.setCurrentRow(0);self.assertFalse(marker.exists())
                with patch.object(QMessageBox,'question',return_value=QMessageBox.StandardButton.Yes):dialog.test()
                loop=QEventLoop();timer=QTimer();timer.timeout.connect(lambda:loop.quit() if dialog.process is None else None);timer.start(10);QTimer.singleShot(5000,loop.quit);loop.exec();timer.stop()
                self.assertIsNone(dialog.process);self.assertTrue(marker.exists());self.assertIn('Initialization response: Fake',dialog.status.text());self.assertIn('tools',dialog.status.text());dialog.close()
            finally:window.close();app.processEvents();store.db.close()

    def test_remote_credential_uses_keyring_and_is_not_reused_for_changed_url(self):
        os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
        from PySide6.QtWidgets import QApplication
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
                dialog.close()
            finally:window.close();app.processEvents();store.db.close()
