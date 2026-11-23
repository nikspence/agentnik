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

    def test_state_only_continuation_preserves_opaque_state(self):
        import time
        calls=[]
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def do_POST(self):
                request=json.loads(self.rfile.read(int(self.headers['Content-Length'])));method=request['method'];calls.append((method,request['params'],time.monotonic()))
                if method=='initialize':self.send_response(400);self.send_header('Content-Length','0');self.end_headers();return
                if method=='server/discover':result={'supportedVersions':[PROTOCOL],'capabilities':{'tools':{}}}
                elif method=='tools/list':result={'tools':[{'name':'work','inputSchema':{'type':'object'}}]}
                elif method=='tools/call':result={'content':[{'type':'text','text':'done'}]} if request['params'].get('requestState')=='opaque-private-state' else {'resultType':'input_required','requestState':'opaque-private-state'}
                else:raise AssertionError(method)
                payload=json.dumps({'jsonrpc':'2.0','id':request['id'],'result':result}).encode();self.send_response(200);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(payload)));self.end_headers();self.wfile.write(payload)
        server=ThreadingHTTPServer(('127.0.0.1',0),Handler);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        session=RemoteSession('http://127.0.0.1:'+str(server.server_port)+'/mcp','',timeout_seconds=5,prefer_modern=False);loop=QEventLoop();out=[];forms=[]
        session.discovered.connect(lambda info:session.call(info['tool_details'][0],{}));session.elicitation_requested.connect(forms.append)
        session.called.connect(lambda value:(out.append(value),loop.quit()));session.ended.connect(lambda value:(out.append(value),loop.quit()))
        timer=QTimer();timer.setSingleShot(True);timer.timeout.connect(loop.quit);timer.start(7000);session.start()
        try:
            loop.exec();timer.stop();self.assertEqual(out[0]['call_result']['content'][0]['text'],'done');self.assertFalse(forms);self.assertNotIn('opaque-private-state',str(out))
            invoked=[call for call in calls if call[0]=='tools/call'];self.assertEqual(len(invoked),2);self.assertEqual(invoked[1][1]['inputResponses'],{});self.assertGreaterEqual(invoked[1][2]-invoked[0][2],.2)
        finally:session.shutdown();server.shutdown();server.server_close();thread.join(2)

    def test_stopping_during_state_wait_does_not_continue(self):
        calls=[]
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def do_POST(self):
                request=json.loads(self.rfile.read(int(self.headers['Content-Length'])));method=request['method'];calls.append(method)
                if method=='initialize':self.send_response(400);self.send_header('Content-Length','0');self.end_headers();return
                if method=='server/discover':result={'supportedVersions':[PROTOCOL],'capabilities':{'tools':{}}}
                elif method=='tools/list':result={'tools':[{'name':'work','inputSchema':{'type':'object'}}]}
                elif method=='tools/call':result={'resultType':'input_required','requestState':'opaque-private-state'}
                else:raise AssertionError(method)
                payload=json.dumps({'jsonrpc':'2.0','id':request['id'],'result':result}).encode();self.send_response(200);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(payload)));self.end_headers();self.wfile.write(payload)
        server=ThreadingHTTPServer(('127.0.0.1',0),Handler);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        session=RemoteSession('http://127.0.0.1:'+str(server.server_port)+'/mcp','',timeout_seconds=5,prefer_modern=False);loop=QEventLoop();out=[]
        session.discovered.connect(lambda info:session.call(info['tool_details'][0],{}));session.ended.connect(out.append)
        def check():
            if session.state_timer.isActive():session.stop();QTimer.singleShot(400,loop.quit)
            else:QTimer.singleShot(10,check)
        timer=QTimer();timer.setSingleShot(True);timer.timeout.connect(loop.quit);timer.start(7000);session.start();QTimer.singleShot(10,check)
        try:
            loop.exec();timer.stop();self.assertTrue(out[0]['call_uncertain']);self.assertEqual(calls.count('tools/call'),1);self.assertFalse(session.state_timer.isActive());self.assertNotIn('opaque-private-state',str(out))
        finally:session.shutdown();server.shutdown();server.server_close();thread.join(2)

    def test_empty_input_map_continues_without_state(self):
        calls=[]
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def do_POST(self):
                request=json.loads(self.rfile.read(int(self.headers['Content-Length'])));method=request['method'];calls.append(request)
                if method=='initialize':self.send_response(400);self.send_header('Content-Length','0');self.end_headers();return
                if method=='server/discover':result={'supportedVersions':[PROTOCOL],'capabilities':{'tools':{}}}
                elif method=='tools/list':result={'tools':[{'name':'work','inputSchema':{'type':'object'}}]}
                elif method=='tools/call':result={'content':[{'type':'text','text':'done'}]} if 'inputResponses' in request['params'] else {'resultType':'input_required','inputRequests':{}}
                else:raise AssertionError(method)
                payload=json.dumps({'jsonrpc':'2.0','id':request['id'],'result':result}).encode();self.send_response(200);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(payload)));self.end_headers();self.wfile.write(payload)
        server=ThreadingHTTPServer(('127.0.0.1',0),Handler);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        session=RemoteSession('http://127.0.0.1:'+str(server.server_port)+'/mcp','',timeout_seconds=5,prefer_modern=False);loop=QEventLoop();out=[];forms=[]
        session.discovered.connect(lambda info:session.call(info['tool_details'][0],{}));session.elicitation_requested.connect(forms.append)
        session.called.connect(lambda value:(out.append(value),loop.quit()));session.ended.connect(lambda value:(out.append(value),loop.quit()))
        timer=QTimer();timer.setSingleShot(True);timer.timeout.connect(loop.quit);timer.start(7000);session.start()
        try:
            loop.exec();timer.stop();self.assertEqual(out[0]['call_result']['content'][0]['text'],'done');self.assertFalse(forms)
            invoked=[call for call in calls if call['method']=='tools/call'];self.assertEqual(len(invoked),2);self.assertEqual(invoked[1]['params']['inputResponses'],{});self.assertNotIn('requestState',invoked[1]['params']);self.assertNotEqual(invoked[0]['id'],invoked[1]['id'])
        finally:session.shutdown();server.shutdown();server.server_close();thread.join(2)

    def test_modern_task_cancellation_is_acknowledged_without_claiming_completion(self):
        for acknowledge in (True,False):
            with self.subTest(acknowledge=acknowledge):
                calls=[];private_id='private-task-id'
                class Handler(BaseHTTPRequestHandler):
                    def log_message(self,*args):pass
                    def do_POST(self):
                        request=json.loads(self.rfile.read(int(self.headers['Content-Length'])));method=request['method'];calls.append((method,dict(self.headers)))
                        if method=='initialize':self.send_response(400);self.send_header('Content-Length','0');self.end_headers();return
                        if method=='server/discover':result={'supportedVersions':[PROTOCOL],'capabilities':{'tools':{},'extensions':{'io.modelcontextprotocol/tasks':{}}}}
                        elif method=='tools/list':result={'tools':[{'name':'example','inputSchema':{'type':'object'}}]}
                        elif method=='tools/call':result={'resultType':'task','taskId':private_id,'status':'working','createdAt':'2026-01-01T00:00:00Z','lastUpdatedAt':'2026-01-01T00:00:00Z','ttlMs':None,'pollIntervalMs':1000}
                        elif method=='tasks/cancel':result={'resultType':'complete'} if acknowledge else {'resultType':'invalid'}
                        else:raise AssertionError(method)
                        payload=json.dumps({'jsonrpc':'2.0','id':request['id'],'result':result}).encode();self.send_response(200);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(payload)));self.end_headers();self.wfile.write(payload)
                server=ThreadingHTTPServer(('127.0.0.1',0),Handler);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
                session=RemoteSession('http://127.0.0.1:'+str(server.server_port)+'/mcp','fixture-token',timeout_seconds=5,prefer_modern=False);session.elicitation_enabled=True;loop=QEventLoop();out=[];progress=[]
                session.discovered.connect(lambda result:session.call(result['tool_details'][0],{}))
                def on_progress(message):
                    progress.append(message)
                    if message=='MCP task started; awaiting result.':session.shutdown()
                    if message=='MCP task cancellation was requested; completion is not confirmed.':session.stop()
                session.progress.connect(on_progress);session.finished.connect(lambda value:(out.append(value),loop.quit()))
                timer=QTimer();timer.setSingleShot(True);timer.timeout.connect(loop.quit);timer.start(7000);session.start()
                try:
                    loop.exec();timer.stop();self.assertEqual(len(out),1);self.assertEqual(out[0]['modern_task_cancel_ack'],acknowledge);self.assertNotIn('task_cancelled',out[0])
                    self.assertNotIn(private_id,str(out)+str(progress));self.assertEqual([m for m,_ in calls].count('tools/call'),1)
                    cancel=next(headers for method,headers in calls if method=='tasks/cancel');self.assertEqual(cancel['Mcp-Name'],private_id);self.assertEqual(cancel['Authorization'],'Bearer fixture-token')
                finally:session.shutdown();server.shutdown();server.server_close();thread.join(2)

    def test_unstructured_initialization_rejection_probes_modern_without_replaying(self):
        for status in (400,404,405):
            with self.subTest(status=status):
                calls=[]
                class Handler(BaseHTTPRequestHandler):
                    def log_message(self,*args):pass
                    def do_POST(self):
                        request=json.loads(self.rfile.read(int(self.headers['Content-Length'])));calls.append((request['method'],self.headers.get('Authorization')))
                        if request['method']=='initialize':self.send_response(status);self.send_header('Content-Length','0');self.end_headers();return
                        body={'jsonrpc':'2.0','id':request['id'],'result':{'supportedVersions':[PROTOCOL],'capabilities':{}}};payload=json.dumps(body).encode()
                        self.send_response(200);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(payload)));self.end_headers();self.wfile.write(payload)
                server=ThreadingHTTPServer(('127.0.0.1',0),Handler);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
                session=RemoteSession('http://127.0.0.1:'+str(server.server_port)+'/mcp','synthetic-token',timeout_seconds=5,prefer_modern=False);loop=QEventLoop();out=[]
                session.discovered.connect(lambda result:(out.append(result),loop.quit()));session.ended.connect(lambda result:(out.append(result),loop.quit()))
                timer=QTimer();timer.setSingleShot(True);timer.timeout.connect(loop.quit);timer.start(7000);session.start()
                try:
                    loop.exec();timer.stop();self.assertTrue(out);self.assertEqual(out[0]['protocol'],PROTOCOL)
                    self.assertEqual(calls,[('initialize','Bearer synthetic-token'),('server/discover','Bearer synthetic-token')])
                finally:session.shutdown();server.shutdown();server.server_close();thread.join(2)

    def test_json_rpc_initialization_rejection_probes_modern(self):
        for code in (-32600,-32601,-32602,-32020,-32022):
            with self.subTest(code=code):
                calls=[]
                class Handler(BaseHTTPRequestHandler):
                    def log_message(self,*args):pass
                    def do_POST(self):
                        request=json.loads(self.rfile.read(int(self.headers['Content-Length'])));calls.append(request['method'])
                        content={'error':{'code':code,'message':'unsupported'}} if request['method']=='initialize' else {'result':{'supportedVersions':[PROTOCOL],'capabilities':{}}}
                        payload=json.dumps(dict(content,jsonrpc='2.0',id=request['id'])).encode();self.send_response(200);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(payload)));self.end_headers();self.wfile.write(payload)
                server=ThreadingHTTPServer(('127.0.0.1',0),Handler);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
                session=RemoteSession('http://127.0.0.1:'+str(server.server_port)+'/mcp','',timeout_seconds=5,prefer_modern=False);loop=QEventLoop();out=[]
                session.discovered.connect(lambda result:(out.append(result),loop.quit()));session.ended.connect(lambda result:(out.append(result),loop.quit()))
                timer=QTimer();timer.setSingleShot(True);timer.timeout.connect(loop.quit);timer.start(7000);session.start()
                try:
                    loop.exec();timer.stop();self.assertEqual(out[0]['protocol'],PROTOCOL);self.assertEqual(calls,['initialize','server/discover'])
                finally:session.shutdown();server.shutdown();server.server_close();thread.join(2)

    def test_failed_json_rpc_probe_reports_both_codes_without_server_text(self):
        calls=[]
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def do_POST(self):
                request=json.loads(self.rfile.read(int(self.headers['Content-Length'])));calls.append(request['method'])
                code=-32602 if request['method']=='initialize' else -32601
                payload=json.dumps({'jsonrpc':'2.0','id':request['id'],'error':{'code':code,'message':'private server diagnostic'}}).encode()
                self.send_response(200);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(payload)));self.end_headers();self.wfile.write(payload)
        server=ThreadingHTTPServer(('127.0.0.1',0),Handler);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        session=RemoteSession('http://127.0.0.1:'+str(server.server_port)+'/mcp','',timeout_seconds=5,prefer_modern=False);loop=QEventLoop();out=[]
        session.ended.connect(lambda result:(out.append(result),loop.quit()));timer=QTimer();timer.setSingleShot(True);timer.timeout.connect(loop.quit);timer.start(7000);session.start()
        try:
            loop.exec();timer.stop();self.assertEqual(calls,['initialize','server/discover']);self.assertIn('-32602',out[0]['error']);self.assertIn('-32601',out[0]['error']);self.assertNotIn('private',out[0]['error'])
        finally:session.shutdown();server.shutdown();server.server_close();thread.join(2)

    def test_unrelated_or_malformed_json_rpc_error_does_not_probe(self):
        for error in ({'code':-32603,'message':'Internal error'},{'code':-32602}):
            with self.subTest(error=error):
                calls=[]
                class Handler(BaseHTTPRequestHandler):
                    def log_message(self,*args):pass
                    def do_POST(self):
                        request=json.loads(self.rfile.read(int(self.headers['Content-Length'])));calls.append(request['method'])
                        payload=json.dumps({'jsonrpc':'2.0','id':request['id'],'error':error}).encode();self.send_response(200);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(payload)));self.end_headers();self.wfile.write(payload)
                server=ThreadingHTTPServer(('127.0.0.1',0),Handler);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
                session=RemoteSession('http://127.0.0.1:'+str(server.server_port)+'/mcp','',timeout_seconds=5,prefer_modern=False);loop=QEventLoop();out=[]
                session.ended.connect(lambda result:(out.append(result),loop.quit()));timer=QTimer();timer.setSingleShot(True);timer.timeout.connect(loop.quit);timer.start(7000);session.start()
                try:loop.exec();timer.stop();self.assertTrue(out);self.assertEqual(calls,['initialize'])
                finally:session.shutdown();server.shutdown();server.server_close();thread.join(2)

    def test_authentication_rejection_does_not_probe_another_protocol(self):
        calls=[]
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def do_POST(self):
                request=json.loads(self.rfile.read(int(self.headers['Content-Length'])));calls.append(request['method'])
                self.send_response(401);self.send_header('WWW-Authenticate','Bearer');self.send_header('Content-Length','0');self.end_headers()
        server=ThreadingHTTPServer(('127.0.0.1',0),Handler);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        session=RemoteSession('http://127.0.0.1:'+str(server.server_port)+'/mcp','synthetic-token',timeout_seconds=5,prefer_modern=False);loop=QEventLoop();out=[]
        session.ended.connect(lambda result:(out.append(result),loop.quit()));timer=QTimer();timer.setSingleShot(True);timer.timeout.connect(loop.quit);timer.start(7000);session.start()
        try:
            loop.exec();timer.stop();self.assertTrue(out);self.assertIn('bearer token',out[0]['error'].lower());self.assertEqual(calls,['initialize'])
        finally:session.shutdown();server.shutdown();server.server_close();thread.join(2)

    def test_failed_protocol_probe_reports_both_statuses_without_server_text(self):
        calls=[]
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def do_POST(self):
                request=json.loads(self.rfile.read(int(self.headers['Content-Length'])));calls.append(request['method']);status=400 if request['method']=='initialize' else 404
                payload=b'private server diagnostic';self.send_response(status);self.send_header('Content-Length',str(len(payload)));self.end_headers();self.wfile.write(payload)
        server=ThreadingHTTPServer(('127.0.0.1',0),Handler);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        session=RemoteSession('http://127.0.0.1:'+str(server.server_port)+'/mcp','',timeout_seconds=5,prefer_modern=False);loop=QEventLoop();out=[]
        session.ended.connect(lambda result:(out.append(result),loop.quit()));timer=QTimer();timer.setSingleShot(True);timer.timeout.connect(loop.quit);timer.start(7000);session.start()
        try:
            loop.exec();timer.stop();self.assertTrue(out);self.assertIn('HTTP 400',out[0]['error']);self.assertIn('HTTP 404',out[0]['error']);self.assertNotIn('private',out[0]['error']);self.assertEqual(calls,['initialize','server/discover'])
        finally:session.shutdown();server.shutdown();server.server_close();thread.join(2)

    def test_access_rate_and_server_failures_do_not_trigger_protocol_probe(self):
        for status in (403,429,500):
            with self.subTest(status=status):
                calls=[]
                class Handler(BaseHTTPRequestHandler):
                    def log_message(self,*args):pass
                    def do_POST(self):
                        request=json.loads(self.rfile.read(int(self.headers['Content-Length'])));calls.append(request['method'])
                        self.send_response(status);self.send_header('Content-Length','0');self.end_headers()
                server=ThreadingHTTPServer(('127.0.0.1',0),Handler);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
                session=RemoteSession('http://127.0.0.1:'+str(server.server_port)+'/mcp','',timeout_seconds=5,prefer_modern=False);loop=QEventLoop();out=[]
                session.ended.connect(lambda result:(out.append(result),loop.quit()));timer=QTimer();timer.setSingleShot(True);timer.timeout.connect(loop.quit);timer.start(7000);session.start()
                try:loop.exec();timer.stop();self.assertTrue(out);self.assertEqual(calls,['initialize'])
                finally:session.shutdown();server.shutdown();server.server_close();thread.join(2)

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
                    if method=='server/discover':result={'supportedVersions':[PROTOCOL],'capabilities':{'tools':{},'extensions':{'io.modelcontextprotocol/tasks':{}}}}
                    elif method=='tools/list':result={'tools':[{'name':'echo','inputSchema':{'type':'object','properties':{'region':{'type':'string','x-mcp-header':'Region'}},'required':['region']}}]}
                    elif method=='tools/call':
                        assert self.headers['Mcp-Name']=='echo'
                        assert self.headers['Mcp-Param-Region']=='=?base64?7ZWc6riA?='
                        assert 'io.modelcontextprotocol/tasks' not in request['params']['_meta']['io.modelcontextprotocol/clientCapabilities'].get('extensions',{})
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
        session=RemoteSession('http://127.0.0.1:'+str(server.server_port)+'/mcp','',timeout_seconds=5,prefer_modern=False);loop=QEventLoop();out=[]
        def discovered(result):
            self.assertEqual(result['protocol'],PROTOCOL)
            self.assertTrue(result['task_extension_advertised']);self.assertFalse(result['task_capabilities']['tool_calls'])
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
        session=RemoteSession('http://127.0.0.1:'+str(server.server_port)+'/mcp','',timeout_seconds=5,prefer_modern=False);loop=QEventLoop();out=[]
        session.discovered.connect(lambda info:session.call(info['tool_details'][0],{}));session.called.connect(lambda result:(out.append(result),loop.quit()));session.ended.connect(lambda result:(out.append(result),loop.quit()))
        timer=QTimer();timer.setSingleShot(True);timer.timeout.connect(loop.quit);timer.start(7000);session.start()
        try:
            loop.exec();timer.stop();self.assertTrue(out[0]['call_uncertain']);self.assertEqual(calls.count('tools/call'),1);self.assertNotIn('GET',calls);self.assertNotIn('notifications/cancelled',calls)
        finally:session.shutdown();server.shutdown();server.server_close();thread.join(2)

    def test_input_required_reports_uncertainty_without_continuation(self):
        calls=[]
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def do_POST(self):
                request=json.loads(self.rfile.read(int(self.headers['Content-Length'])));method=request['method'];calls.append(method)
                if method=='initialize':status=400;body={'jsonrpc':'2.0','id':request['id'],'error':{'code':-32020,'message':'headers required'}}
                else:
                    status=200
                    if method=='server/discover':result={'supportedVersions':[PROTOCOL],'capabilities':{'tools':{}}}
                    elif method=='tools/list':result={'tools':[{'name':'work','inputSchema':{'type':'object'}}]}
                    elif method=='tools/call':result={'resultType':'input_required','inputRequests':{'question':{'method':'elicitation/create','params':{'message':'private-server-text'}}},'requestState':'private-state'}
                    else:raise AssertionError(method)
                    body={'jsonrpc':'2.0','id':request['id'],'result':result}
                payload=json.dumps(body).encode();self.send_response(status);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(payload)));self.end_headers();self.wfile.write(payload)
        server=ThreadingHTTPServer(('127.0.0.1',0),Handler);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        session=RemoteSession('http://127.0.0.1:'+str(server.server_port)+'/mcp','',timeout_seconds=5,prefer_modern=False);loop=QEventLoop();out=[]
        session.discovered.connect(lambda info:session.call(info['tool_details'][0],{}));session.called.connect(lambda result:(out.append(('called',result)),loop.quit()));session.ended.connect(lambda result:(out.append(('ended',result)),loop.quit()))
        timer=QTimer();timer.setSingleShot(True);timer.timeout.connect(loop.quit);timer.start(7000);session.start()
        try:
            loop.exec();timer.stop();self.assertEqual(out[0][0],'ended');self.assertIn('interactive input',out[0][1]['error']);self.assertTrue(out[0][1]['call_uncertain']);self.assertNotIn('private',str(out));self.assertEqual(calls.count('tools/call'),1)
        finally:session.shutdown();server.shutdown();server.server_close();thread.join(2)

    def test_form_answer_continues_original_call_with_new_identifier(self):
        calls=[]
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def do_POST(self):
                request=json.loads(self.rfile.read(int(self.headers['Content-Length'])));method=request['method'];calls.append(request)
                if method=='initialize':status=400;body={'jsonrpc':'2.0','id':request['id'],'error':{'code':-32020,'message':'headers required'}}
                else:
                    status=200
                    if method=='server/discover':result={'supportedVersions':[PROTOCOL],'capabilities':{'tools':{}}}
                    elif method=='tools/list':result={'tools':[{'name':'work','inputSchema':{'type':'object'}}]}
                    elif method=='tools/call' and 'inputResponses' not in request['params']:
                        result={'resultType':'input_required','requestState':'opaque-state','inputRequests':{'question':{'method':'elicitation/create','params':{'message':'Choose','requestedSchema':{'type':'object','properties':{'choice':{'type':'string'}},'required':['choice']}}}}}
                    elif method=='tools/call':result={'content':[{'type':'text','text':'continued'}]}
                    else:raise AssertionError(method)
                    body={'jsonrpc':'2.0','id':request['id'],'result':result}
                payload=json.dumps(body).encode();self.send_response(status);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(payload)));self.end_headers();self.wfile.write(payload)
        server=ThreadingHTTPServer(('127.0.0.1',0),Handler);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        session=RemoteSession('http://127.0.0.1:'+str(server.server_port)+'/mcp','',timeout_seconds=5,prefer_modern=False);session.elicitation_enabled=True;loop=QEventLoop();out=[]
        session.discovered.connect(lambda info:session.call(info['tool_details'][0],{}));session.elicitation_requested.connect(lambda _:session.continue_elicitation({'question':{'action':'accept','content':{'choice':'yes'}}}));session.called.connect(lambda result:(out.append(result),loop.quit()));session.ended.connect(lambda result:(out.append(result),loop.quit()))
        timer=QTimer();timer.setSingleShot(True);timer.timeout.connect(loop.quit);timer.start(7000);session.start()
        try:
            loop.exec();timer.stop();self.assertEqual(out[0]['call_result']['content'][0]['text'],'continued')
            requests=[item for item in calls if item['method']=='tools/call'];self.assertEqual(len(requests),2);self.assertNotEqual(requests[0]['id'],requests[1]['id']);self.assertEqual(requests[1]['params']['requestState'],'opaque-state');self.assertEqual(requests[1]['params']['inputResponses']['question']['content'],{'choice':'yes'});self.assertEqual(requests[0]['params']['_meta']['io.modelcontextprotocol/clientCapabilities'],{'elicitation':{'form':{},'url':{}}})
        finally:session.shutdown();server.shutdown();server.server_close();thread.join(2)

    def test_subscription_requires_acknowledgement_and_matching_request_id(self):
        session=RemoteSession('https://example.com/mcp','',prefer_modern=False);session.modern=True;session.subscription_id=9
        session.result={'subscription_filters':{'resourcesListChanged':True,'promptsListChanged':True}}
        session.resource_items=[{'uri':'test://old'}];session.template_items=[{'uriTemplate':'test://{item}'}];session.prompt_items=[{'name':'old'}]
        events=[];session.progress.connect(events.append)
        def message(method,subscription_id,**extra):
            return json.dumps({'jsonrpc':'2.0','method':method,'params':dict(extra,_meta={'io.modelcontextprotocol/subscriptionId':subscription_id})}).encode()
        session.server_stream_event(message('notifications/subscriptions/acknowledged',9,notifications={'resourcesListChanged':True,'promptsListChanged':True}))
        self.assertEqual(session.subscription_ack,{'resourcesListChanged','promptsListChanged'})
        session.server_stream_event(message('notifications/resources/list_changed',9))
        self.assertEqual(session.resource_items,[]);self.assertEqual(session.template_items,[]);self.assertEqual(session.prompt_items,[{'name':'old'}])
        session.server_stream_event(message('notifications/prompts/list_changed',10))
        self.assertEqual(session.prompt_items,[]);self.assertIsNone(session.subscription_ack);self.assertTrue(any('invalid message' in item for item in events))
        session.closed=True

    def test_subscription_does_not_accept_unacknowledged_notification(self):
        session=RemoteSession('https://example.com/mcp','',prefer_modern=False);session.modern=True;session.subscription_id=9;session.result={'subscription_filters':{'resourcesListChanged':True}}
        session.resource_items=[{'uri':'test://old'}];session.prompt_items=[{'name':'old'}];events=[];session.progress.connect(events.append)
        session.server_stream_event(json.dumps({'jsonrpc':'2.0','method':'notifications/resources/list_changed','params':{'_meta':{'io.modelcontextprotocol/subscriptionId':9}}}).encode())
        self.assertEqual(session.resource_items,[]);self.assertEqual(session.prompt_items,[]);self.assertTrue(events);session.closed=True

    def test_subscription_acknowledgement_of_subset_clears_uncovered_listings(self):
        session=RemoteSession('https://example.com/mcp','',prefer_modern=False);session.modern=True;session.subscription_id=9
        session.result={'subscription_filters':{'resourcesListChanged':True,'promptsListChanged':True}}
        session.resource_items=[{'uri':'test://old'}];session.prompt_items=[{'name':'old'}];events=[];session.progress.connect(events.append)
        session.server_stream_event(json.dumps({'jsonrpc':'2.0','method':'notifications/subscriptions/acknowledged','params':{'notifications':{'resourcesListChanged':True},'_meta':{'io.modelcontextprotocol/subscriptionId':9}}}).encode())
        self.assertEqual(session.resource_items,[{'uri':'test://old'}]);self.assertEqual(session.prompt_items,[]);self.assertTrue(any('declined' in text for text in events));session.closed=True

    def test_tool_change_requires_fresh_discovery(self):
        from unittest.mock import Mock
        session=RemoteSession('https://example.com/mcp','',prefer_modern=False);session.modern=True;session.subscription_id=9;session.subscription_ack={'toolsListChanged'};session.stop=Mock()
        session.server_stream_event(json.dumps({'jsonrpc':'2.0','method':'notifications/tools/list_changed','params':{'_meta':{'io.modelcontextprotocol/subscriptionId':9}}}).encode())
        session.stop.assert_called_once();self.assertIn('reconnect',session.stop.call_args.args[0]);session.closed=True

    def test_subscription_disconnect_restarts_without_replay_and_invalidates_lists(self):
        release=threading.Event();finish=threading.Event();listens=[]
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def do_POST(self):
                request=json.loads(self.rfile.read(int(self.headers['Content-Length'])));method=request['method']
                if method=='subscriptions/listen':
                    listens.append((request['id'],self.headers.get('Last-Event-ID')))
                    acknowledgement={'jsonrpc':'2.0','method':'notifications/subscriptions/acknowledged','params':{'_meta':{'io.modelcontextprotocol/subscriptionId':request['id']},'notifications':{'resourcesListChanged':True}}}
                    self.send_response(200);self.send_header('Content-Type','text/event-stream');self.end_headers();self.wfile.write(b'data: '+json.dumps(acknowledgement).encode()+b'\n\n');self.wfile.flush()
                    (release if len(listens)==1 else finish).wait(7);return
                if method=='initialize':status=400;body={'jsonrpc':'2.0','id':request['id'],'error':{'code':-32020,'message':'headers required'}}
                else:
                    status=200
                    if method=='server/discover':result={'supportedVersions':[PROTOCOL],'capabilities':{'resources':{'listChanged':True}}}
                    elif method=='resources/list':result={'resources':[{'uri':'test://old','name':'Old'}]}
                    else:raise AssertionError(method)
                    body={'jsonrpc':'2.0','id':request['id'],'result':result}
                payload=json.dumps(body).encode();self.send_response(status);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(payload)));self.end_headers();self.wfile.write(payload)
        server=ThreadingHTTPServer(('127.0.0.1',0),Handler);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        session=RemoteSession('http://127.0.0.1:'+str(server.server_port)+'/mcp','',timeout_seconds=5,prefer_modern=False);loop=QEventLoop();events=[]
        session.discovered.connect(lambda _:session.list_resources());session.resources.connect(lambda _:release.set())
        session.progress.connect(lambda text:events.append(text));session.ended.connect(lambda _:loop.quit())
        poll=QTimer();poll.timeout.connect(lambda:loop.quit() if len(listens)>=2 and session.subscription_ack is not None else None);poll.start(25)
        timer=QTimer();timer.setSingleShot(True);timer.timeout.connect(loop.quit);timer.start(7000);session.start()
        try:
            loop.exec();timer.stop();poll.stop();self.assertEqual(len(listens),2);self.assertNotEqual(listens[0][0],listens[1][0]);self.assertEqual([item[1] for item in listens],[None,None]);self.assertEqual(session.resource_items,[]);self.assertTrue(any('disconnected' in item for item in events))
        finally:release.set();finish.set();session.shutdown();server.shutdown();server.server_close();thread.join(2)
