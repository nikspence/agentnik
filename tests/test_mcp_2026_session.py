import json
import threading
import unittest
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer

from PySide6.QtCore import QEventLoop,QTimer
from PySide6.QtWidgets import QApplication
from agentnik.mcp_remote import RemoteSession
from agentnik.mcp_2026 import PROTOCOL


class ModernRemoteSession(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.app=QApplication.instance() or QApplication([])

    def test_modern_only_server_discovery_and_call(self):
        calls=[]
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def do_POST(self):
                request=json.loads(self.rfile.read(int(self.headers['Content-Length'])));method=request['method']
                calls.append((method,dict(self.headers),request))
                if method=='initialize':
                    status=400;result={'jsonrpc':'2.0','id':request['id'],'error':{'code':-32020,'message':'missing metadata headers'}}
                else:
                    self.assert_request(request)
                    status=200
                    if method=='server/discover':result={'supportedVersions':[PROTOCOL],'capabilities':{'tools':{}}}
                    elif method=='tools/list':result={'tools':[{'name':'echo','inputSchema':{'type':'object','properties':{'region':{'type':'string','x-mcp-header':'Region'}},'required':['region']}}]}
                    elif method=='tools/call':
                        assert self.headers['Mcp-Name']=='echo'
                        assert self.headers['Mcp-Param-Region']=='=?base64?7ZWc6riA?='
                        result={'content':[{'type':'text','text':'done'}]}
                    else:raise AssertionError(method)
                    result={'jsonrpc':'2.0','id':request['id'],'result':result}
                payload=json.dumps(result).encode();self.send_response(status);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(payload)));self.end_headers();self.wfile.write(payload)
            def assert_request(self,request):
                assert self.headers['MCP-Protocol-Version']==PROTOCOL
                assert self.headers['Mcp-Method']==request['method']
                assert request['params']['_meta']['io.modelcontextprotocol/protocolVersion']==PROTOCOL
                assert self.headers.get('Mcp-Session-Id') is None
            def do_GET(self):calls.append(('GET',{},{}));self.send_error(405)
            def do_DELETE(self):calls.append(('DELETE',{},{}));self.send_error(405)
        server=ThreadingHTTPServer(('127.0.0.1',0),Handler);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        session=RemoteSession('http://127.0.0.1:'+str(server.server_port)+'/mcp','',timeout_seconds=5);loop=QEventLoop();out=[]
        def discovered(result):
            self.assertEqual(result['protocol'],PROTOCOL)
            session.call(result['tool_details'][0],{'region':'한글'})
        session.discovered.connect(discovered);session.called.connect(lambda result:(out.append(result),loop.quit()));session.ended.connect(lambda result:(out.append(result),loop.quit()))
        timer=QTimer();timer.setSingleShot(True);timer.timeout.connect(loop.quit);timer.start(7000);session.start()
        try:
            loop.exec();timer.stop();self.assertEqual(out[0]['call_result']['content'][0]['text'],'done')
            self.assertEqual([call[0] for call in calls],['initialize','server/discover','tools/list','tools/list','tools/call'])
        finally:session.shutdown();server.shutdown();server.server_close();thread.join(2)

    def test_interrupted_modern_call_is_not_replayed_or_resumed(self):
        calls=[]
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def do_GET(self):calls.append('GET');self.send_error(405)
            def do_POST(self):
                request=json.loads(self.rfile.read(int(self.headers['Content-Length'])));method=request['method'];calls.append(method)
                if method=='tools/call':
                    self.send_response(200);self.send_header('Content-Type','text/event-stream');self.end_headers();self.wfile.write(b'id: cursor\ndata:\n\ndata: {"partial"');self.wfile.flush();return
                if method=='initialize':status=400;body={'jsonrpc':'2.0','id':request['id'],'error':{'code':-32020,'message':'headers required'}}
                else:
                    status=200;result={'supportedVersions':[PROTOCOL],'capabilities':{'tools':{}}} if method=='server/discover' else {'tools':[{'name':'work','inputSchema':{'type':'object'}}]}
                    body={'jsonrpc':'2.0','id':request['id'],'result':result}
                payload=json.dumps(body).encode();self.send_response(status);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(payload)));self.end_headers();self.wfile.write(payload)
        server=ThreadingHTTPServer(('127.0.0.1',0),Handler);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        session=RemoteSession('http://127.0.0.1:'+str(server.server_port)+'/mcp','',timeout_seconds=5);loop=QEventLoop();out=[]
        session.discovered.connect(lambda info:session.call(info['tool_details'][0],{}));session.called.connect(lambda result:(out.append(result),loop.quit()));session.ended.connect(lambda result:(out.append(result),loop.quit()))
        timer=QTimer();timer.setSingleShot(True);timer.timeout.connect(loop.quit);timer.start(7000);session.start()
        try:
            loop.exec();timer.stop();self.assertTrue(out[0]['call_uncertain']);self.assertEqual(calls.count('tools/call'),1);self.assertNotIn('GET',calls);self.assertNotIn('notifications/cancelled',calls)
        finally:session.shutdown();server.shutdown();server.server_close();thread.join(2)
