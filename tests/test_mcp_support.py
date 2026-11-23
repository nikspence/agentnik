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
    def test_remote_initialization_sse_completes_without_stream_closure(self):
        import threading
        from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
        from PySide6.QtCore import QEventLoop,QTimer
        from PySide6.QtWidgets import QApplication
        from agentnik.mcp_remote import RemoteSession
        app=QApplication.instance() or QApplication([])
        for mode in ('result','ping','unsupported'):
            with self.subTest(mode=mode):
                release=threading.Event();ping_answered=threading.Event();requests=[];answers=[]
                class Handler(BaseHTTPRequestHandler):
                    def log_message(self,*args):pass
                    def do_POST(self,mode=mode,release=release,requests=requests,answers=answers,ping_answered=ping_answered):
                        body=json.loads(self.rfile.read(int(self.headers['Content-Length'])));method=body.get('method');requests.append(method)
                        if method is None:
                            answers.append((body,self.headers.get('Mcp-Session-Id'),self.headers.get('MCP-Protocol-Version')));self.send_response(202);self.end_headers();ping_answered.set();return
                        if method=='notifications/initialized':self.send_response(202);self.end_headers();return
                        if method=='initialize':
                            result={'jsonrpc':'2.0','id':body['id'],'result':{'protocolVersion':PROTOCOL,'serverInfo':{'name':'Fixture','version':'1'},'capabilities':{'tools':{}}}}
                            self.send_response(200);self.send_header('Content-Type','text/event-stream');self.send_header('Mcp-Session-Id','session-one');self.end_headers()
                            if mode!='result':
                                self.wfile.write(b'data: '+json.dumps({'jsonrpc':'2.0','id':'early','method':'ping' if mode=='ping' else 'sampling/createMessage'}).encode()+b'\n\n');self.wfile.flush()
                                if mode!='ping' or not ping_answered.wait(3):release.wait(5);return
                            self.wfile.write(b'data: '+json.dumps(result).encode()+b'\n\n');self.wfile.flush();release.wait(5);return
                        payload=json.dumps({'jsonrpc':'2.0','id':body['id'],'result':{'tools':[]}}).encode();self.send_response(200);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(payload)));self.end_headers();self.wfile.write(payload)
                    def do_GET(self):self.send_response(405);self.end_headers()
                    def do_DELETE(self):self.send_response(204);self.end_headers()
                server=ThreadingHTTPServer(('127.0.0.1',0),Handler);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
                session=RemoteSession('http://127.0.0.1:'+str(server.server_port)+'/mcp','',timeout_seconds=2,prefer_modern=False);loop=QEventLoop();out=[]
                session.discovered.connect(lambda value:(out.append(('discovered',value)),loop.quit()));session.ended.connect(lambda value:(out.append(('ended',value)),loop.quit()));session.start();timer=QTimer();timer.setSingleShot(True);timer.timeout.connect(loop.quit);timer.start(4000)
                try:
                    loop.exec();timer.stop();self.assertTrue(out);self.assertFalse(release.is_set())
                    if mode in ('result','ping'):
                        self.assertEqual(out[0][0],'discovered',out);self.assertEqual(session.session,'session-one');self.assertIn('notifications/initialized',requests)
                        if mode=='ping':self.assertEqual(answers,[({'jsonrpc':'2.0','id':'early','result':{}},'session-one',PROTOCOL)])
                    else:self.assertEqual(out[0][0],'ended');self.assertIn('during initialization',out[0][1]['error']);self.assertEqual(requests,['initialize'])
                finally:release.set();session.shutdown();server.shutdown();server.server_close();thread.join(2)

    def test_remote_tool_response_completes_before_stream_closes(self):
        import threading
        from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
        from PySide6.QtCore import QEventLoop,QTimer
        from PySide6.QtWidgets import QApplication
        from agentnik.mcp_remote import RemoteSession
        app=QApplication.instance() or QApplication([]);release=threading.Event();calls=[]
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def do_POST(self):
                body=json.loads(self.rfile.read(int(self.headers['Content-Length'])));method=body['method'];calls.append(method)
                if method=='notifications/initialized':self.send_response(202);self.end_headers();return
                if method=='tools/call':
                    payload=json.dumps({'jsonrpc':'2.0','id':body['id'],'result':{'content':[{'type':'text','text':'complete'}]}}).encode()
                    self.send_response(200);self.send_header('Content-Type','text/event-stream');self.end_headers();self.wfile.write(b'data: '+payload+b'\n\n');self.wfile.flush();release.wait(6);return
                result={'protocolVersion':PROTOCOL,'serverInfo':{'name':'Fixture','version':'1'},'capabilities':{'tools':{}}} if method=='initialize' else {'tools':[{'name':'work','inputSchema':{'type':'object'}}]}
                payload=json.dumps({'jsonrpc':'2.0','id':body['id'],'result':result}).encode();self.send_response(200);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(payload)));self.send_header('Mcp-Session-Id','session-one');self.end_headers();self.wfile.write(payload)
            def do_GET(self):self.send_response(405);self.end_headers()
            def do_DELETE(self):self.send_response(204);self.end_headers()
        server=ThreadingHTTPServer(('127.0.0.1',0),Handler);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        session=RemoteSession('http://127.0.0.1:'+str(server.server_port)+'/mcp','',timeout_seconds=3,prefer_modern=False);loop=QEventLoop();out=[]
        session.discovered.connect(lambda info:session.call(info['tool_details'][0],{}));session.called.connect(lambda value:(out.append(value),loop.quit()));session.ended.connect(lambda value:(out.append(value),loop.quit()));session.start();timer=QTimer();timer.setSingleShot(True);timer.timeout.connect(loop.quit);timer.start(5000)
        try:
            loop.exec();timer.stop();self.assertTrue(out);self.assertEqual(out[0]['call_result']['content'][0]['text'],'complete');self.assertFalse(release.is_set());self.assertEqual(calls.count('tools/call'),1)
        finally:release.set();session.shutdown();server.shutdown();server.server_close();thread.join(2)

    def test_remote_stream_answers_server_ping_without_interrupting_tool(self):
        import threading
        from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
        from PySide6.QtCore import QEventLoop,QTimer
        from PySide6.QtWidgets import QApplication
        from agentnik.mcp_remote import RemoteSession
        app=QApplication.instance() or QApplication([])
        for mode in ('same-id','string-id','unsupported'):
            with self.subTest(mode=mode):
                received=[];ping_answered=threading.Event()
                class Handler(BaseHTTPRequestHandler):
                    def log_message(self,*args):pass
                    def do_POST(self):
                        body=json.loads(self.rfile.read(int(self.headers['Content-Length'])));method=body.get('method')
                        if method is None:
                            received.append((body,self.headers.get('Mcp-Session-Id'),self.headers.get('Authorization'),self.headers.get('MCP-Protocol-Version')));ping_answered.set();self.send_response(202);self.end_headers();return
                        if method=='notifications/initialized':self.send_response(202);self.end_headers();return
                        if method=='initialize':result={'protocolVersion':PROTOCOL,'serverInfo':{'name':'Fake','version':'1'},'capabilities':{'tools':{}}}
                        elif method=='tools/list':result={'tools':[{'name':'work','inputSchema':{'type':'object'}}]}
                        elif method=='tools/call':
                            ping={'jsonrpc':'2.0','id':body['id'] if mode=='same-id' else 'server-ping','method':'sampling/createMessage' if mode=='unsupported' else 'ping'}
                            self.send_response(200);self.send_header('Content-Type','text/event-stream');self.end_headers();self.wfile.write(b'data: '+json.dumps(ping).encode()+b'\n\n');self.wfile.flush()
                            if ping_answered.wait(4):self.wfile.write(b'data: '+json.dumps({'jsonrpc':'2.0','id':body['id'],'result':{'content':[{'type':'text','text':'done'}]}}).encode()+b'\n\n');self.wfile.flush()
                            return
                        else:raise AssertionError(method)
                        payload=json.dumps({'jsonrpc':'2.0','id':body['id'],'result':result}).encode();self.send_response(200);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(payload)));self.send_header('Mcp-Session-Id','session-one');self.end_headers();self.wfile.write(payload)
                    def do_DELETE(self):self.send_response(204);self.end_headers()
                server=ThreadingHTTPServer(('127.0.0.1',0),Handler);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
                session=RemoteSession('http://127.0.0.1:'+str(server.server_port)+'/mcp','fixture-token',timeout_seconds=5,prefer_modern=False);loop=QEventLoop();out=[]
                session.discovered.connect(lambda info:session.call(info['tool_details'][0],{}));session.called.connect(lambda value:(out.append(value),loop.quit()));session.ended.connect(lambda value:(out.append(value),loop.quit()));session.start();QTimer.singleShot(7000,loop.quit)
                try:
                    loop.exec();self.assertEqual(out[0]['call_result']['content'][0]['text'],'done');self.assertEqual(len(received),1)
                    response,session_header,auth,protocol=received[0]
                    if mode=='unsupported':self.assertEqual(response['error']['code'],-32601)
                    else:self.assertEqual(response['result'],{})
                    self.assertEqual(response['id'],4 if mode=='same-id' else 'server-ping');self.assertEqual(session_header,'session-one');self.assertEqual(auth,'Bearer fixture-token');self.assertEqual(protocol,PROTOCOL)
                finally:session.shutdown();server.shutdown();server.server_close();thread.join(2)

    def test_remote_server_ping_rejects_invalid_or_duplicate_requests(self):
        from PySide6.QtWidgets import QApplication
        from agentnik.mcp_remote import RemoteSession,response_message
        app=QApplication.instance() or QApplication([]);session=RemoteSession('https://example.com/mcp','',prefer_modern=False)
        invalid=[{'id':True,'method':'ping'},{'id':'x','method':''},{'id':'x','method':'ping','params':[]},{'id':'x','method':'ping','result':{}},{'id':'x'*129,'method':'ping'}]
        session.server_pings[('int',7)]={'jsonrpc':'2.0','id':7,'method':'ping'};invalid.append({'id':7,'method':'ping'})
        for request in invalid:
            with self.subTest(request=request),self.assertRaises(ValueError):session.server_request(request)
        ping=b'data: {"jsonrpc":"2.0","id":7,"method":"ping"}\n\n';final=b'data: {"jsonrpc":"2.0","id":7,"result":{}}\n\n'
        self.assertEqual(response_message(ping+final,'text/event-stream',7,on_server_request=session.verify_server_ping)['result'],{})
        with self.assertRaises(ValueError):response_message(ping+final,'text/event-stream',7)
        session.closed=True

    def test_schema_pattern_validates_and_bounds_untrusted_expressions(self):
        import time
        from agentnik.mcp_schema import validate_tool_arguments,MCPArgumentValidationError
        for dialect in ('https://json-schema.org/draft/2020-12/schema','http://json-schema.org/draft-07/schema'):
            schema={'$schema':dialect,'type':'object','properties':{'code':{'type':'string','pattern':'^[A-Z]{2}-[0-9]{3}$'}},'required':['code']}
            self.assertTrue(validate_tool_arguments(schema,{'code':'AB-123'}))
            with self.assertRaises(MCPArgumentValidationError):validate_tool_arguments(schema,{'code':'private-value'})
        nested={'type':'object','properties':{'x':{'anyOf':[{'type':'string','pattern':'^ok$'},{'type':'integer'}]}}}
        self.assertTrue(validate_tool_arguments(nested,{'x':'ok'}))
        with self.assertRaises(MCPArgumentValidationError):validate_tool_arguments(nested,{'x':'bad'})
        for pattern in ('[','x'*513,'(a{1000}){1000}','a{100000000}','a{,100000000}',r'\\{100000000}'):
            with self.subTest(pattern=pattern[:30]),self.assertRaises(ValueError):validate_tool_arguments({'type':'object','properties':{'x':{'type':'string','pattern':pattern}}},{'x':'a'})
        schema={'type':'object','properties':{'x':{'type':'string','pattern':'^(a|aa)+$'}}}
        referenced={'$schema':'https://json-schema.org/draft/2020-12/schema','type':'object','$defs':{'s':{'type':'string','pattern':'^(a|aa)+$'}},'properties':{'x':{'$ref':'#/$defs/s'}}}
        for guarded in (schema,referenced):
            start=time.monotonic()
            with self.assertRaises(ValueError) as caught:validate_tool_arguments(guarded,{'x':'a'*10000+'!'})
            self.assertLess(time.monotonic()-start,2);self.assertNotIn('aaaa',str(caught.exception))
        import threading
        results=[]
        def valid():results.append(validate_tool_arguments(schema,{'x':'a'}))
        def timed_out():
            try:validate_tool_arguments(schema,{'x':'a'*10000+'!'})
            except ValueError:results.append(True)
        threads=[threading.Thread(target=timed_out),threading.Thread(target=valid)]
        for thread in threads:thread.start()
        for thread in threads:thread.join(2)
        self.assertTrue(all(not thread.is_alive() for thread in threads));self.assertEqual(results,[True,True])

    def test_remote_2025_form_request_on_both_event_streams(self):
        import threading
        from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
        from PySide6.QtCore import QEventLoop,QTimer
        from PySide6.QtWidgets import QApplication
        from agentnik.mcp_remote import RemoteSession
        app=QApplication.instance() or QApplication([])
        for stream in ('response','standalone'):
            for action in ('accept','decline'):
                with self.subTest(stream=stream,action=action):
                    sent=threading.Event();answered=threading.Event();received=[]
                    class Handler(BaseHTTPRequestHandler):
                        def log_message(self,*args):pass
                        def do_POST(self):
                            body=json.loads(self.rfile.read(int(self.headers['Content-Length'])));method=body.get('method')
                            if method is None:
                                received.append((body,self.headers.get('Mcp-Session-Id'),self.headers.get('Authorization'),self.headers.get('MCP-Protocol-Version')));self.send_response(202);self.end_headers();answered.set();return
                            if method=='notifications/initialized':self.send_response(202);self.end_headers();return
                            if method=='initialize':
                                assert body['params']['capabilities']['elicitation']=={'form':{},'url':{}}
                                result={'protocolVersion':PROTOCOL,'serverInfo':{'name':'Fake','version':'1'},'capabilities':{'tools':{}}}
                            elif method=='tools/list':result={'tools':[{'name':'work','inputSchema':{'type':'object'}}]}
                            elif method=='tools/call':
                                self.send_response(200);self.send_header('Content-Type','text/event-stream');self.end_headers()
                                request={'jsonrpc':'2.0','id':'input','method':'elicitation/create','params':{'message':'Choose','requestedSchema':{'type':'object','properties':{'choice':{'type':'string'}},'required':['choice']}}}
                                if stream=='response':self.wfile.write(b'data: '+json.dumps(request).encode()+b'\n\n');self.wfile.flush()
                                else:sent.set()
                                if answered.wait(5):self.wfile.write(b'data: '+json.dumps({'jsonrpc':'2.0','id':body['id'],'result':{'content':[{'type':'text','text':'done'}]}}).encode()+b'\n\n');self.wfile.flush()
                                return
                            else:raise AssertionError(method)
                            payload=json.dumps({'jsonrpc':'2.0','id':body['id'],'result':result}).encode();self.send_response(200);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(payload)));self.send_header('Mcp-Session-Id','session-one');self.end_headers();self.wfile.write(payload)
                        def do_GET(self):
                            if stream!='standalone':self.send_response(405);self.end_headers();return
                            self.send_response(200);self.send_header('Content-Type','text/event-stream');self.end_headers();self.wfile.write(b': ready\n\n');self.wfile.flush()
                            if sent.wait(5):
                                request={'jsonrpc':'2.0','id':'input','method':'elicitation/create','params':{'message':'Choose','requestedSchema':{'type':'object','properties':{'choice':{'type':'string'}},'required':['choice']}}}
                                self.wfile.write(b'id: event-one\ndata: '+json.dumps(request).encode()+b'\n\n');self.wfile.flush();answered.wait(5)
                        def do_DELETE(self):self.send_response(204);self.end_headers()
                    server=ThreadingHTTPServer(('127.0.0.1',0),Handler);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
                    session=RemoteSession('http://127.0.0.1:'+str(server.server_port)+'/mcp','fixture-token',timeout_seconds=5,prefer_modern=False);session.elicitation_enabled=True;loop=QEventLoop();out=[];presented=[]
                    session.discovered.connect(lambda info:session.call(info['tool_details'][0],{}))
                    def request_input(forms):
                        presented.append(forms);self.assertFalse(session.timer.isActive());self.assertEqual(received,[])
                        response={'action':'accept','content':{'choice':'yes'}} if action=='accept' else {'action':'decline'}
                        QTimer.singleShot(50,lambda:session.continue_elicitation({'request':response}))
                    session.elicitation_requested.connect(request_input);session.called.connect(lambda value:(out.append(value),loop.quit()));session.ended.connect(lambda value:(out.append(value),loop.quit()));session.start();QTimer.singleShot(8000,loop.quit)
                    try:
                        loop.exec();self.assertEqual(out[0]['call_result']['content'][0]['text'],'done');self.assertEqual(len(presented),1);self.assertEqual(len(received),1)
                        response,session_header,auth,protocol=received[0];self.assertEqual(response['id'],'input');self.assertEqual(response['result']['action'],action)
                        if action=='accept':self.assertEqual(response['result']['content'],{'choice':'yes'})
                        self.assertEqual((session_header,auth,protocol),('session-one','Bearer fixture-token',PROTOCOL));self.assertNotIn('yes',str(out))
                    finally:sent.set();answered.set();session.shutdown();server.shutdown();server.server_close();thread.join(2)

    def test_remote_2025_rejects_invalid_and_credential_answers_before_post(self):
        from unittest.mock import Mock
        from PySide6.QtWidgets import QApplication
        from agentnik.mcp_remote import RemoteSession
        from agentnik.mcp_elicitation import parse_input_required
        app=QApplication.instance() or QApplication([])
        pending=parse_input_required({'resultType':'input_required','inputRequests':{'request':{'method':'elicitation/create','params':{'message':'Choose','requestedSchema':{'type':'object','properties':{'choice':{'type':'string'}},'required':['choice']}}}}});pending['legacy_request']=('server-id',False)
        for answer in ({'action':'accept','content':{}},{'action':'accept','content':{'choice':'fixture-token'}}):
            session=RemoteSession('https://example.com/mcp','fixture-token',prefer_modern=False);session.elicitation_pending=pending;session.post_server_response=Mock();session.stop=Mock()
            self.assertFalse(session.continue_elicitation({'request':answer}));session.post_server_response.assert_not_called();session.stop.assert_called_once();session.closed=True

    def test_remote_2025_does_not_repeat_replayed_elicitation(self):
        from unittest.mock import Mock
        from PySide6.QtWidgets import QApplication
        from agentnik.mcp_remote import RemoteSession
        app=QApplication.instance() or QApplication([]);session=RemoteSession('https://example.com/mcp','',prefer_modern=False);session.server_request=Mock()
        request=json.dumps({'jsonrpc':'2.0','id':'input','method':'elicitation/create','params':{}}).encode()
        session.server_stream_event(request,duplicate=True);session.server_request.assert_not_called();session.closed=True

    def test_remote_standalone_stream_invalidates_unrelated_catalogs(self):
        from unittest.mock import Mock
        from PySide6.QtWidgets import QApplication
        from PySide6.QtNetwork import QNetworkRequest
        from agentnik.mcp_remote import RemoteSession
        app=QApplication.instance() or QApplication([]);session=RemoteSession('https://example.com/mcp','',prefer_modern=False);session.phase='call';session.resource_items=[{'uri':'old'}];session.template_items=[{'uriTemplate':'old'}];session.prompt_items=[{'name':'old'}]
        notices=[];session.progress.connect(notices.append);reply=Mock();reply.attribute.return_value=200;reply.header.return_value='text/event-stream';session.server_stream=reply
        events=[{'jsonrpc':'2.0','method':'notifications/resources/list_changed'},{'jsonrpc':'2.0','method':'notifications/prompts/list_changed'}]
        wire=b'\xef\xbb\xbf'+b''.join(b'data: '+json.dumps(event).encode()+b'\r\n\r\n' for event in events)
        reply.readAll.side_effect=[wire[:9],wire[9:]];session.read_server_stream(reply);self.assertEqual(len(notices),0);session.read_server_stream(reply)
        self.assertEqual(session.resource_items,[]);self.assertEqual(session.template_items,[]);self.assertEqual(session.prompt_items,[]);self.assertEqual(len(notices),2)
        session.phase='resource_list';session.stop=Mock();session.server_stream_event(json.dumps(events[0]).encode());session.stop.assert_called_once()
        session.server_stream=None;session.closed=True

    def test_remote_shutdown_during_response_resume_cancels_original_request(self):
        from unittest.mock import Mock
        from PySide6.QtWidgets import QApplication
        from agentnik.mcp_remote import RemoteSession
        app=QApplication.instance() or QApplication([]);session=RemoteSession('https://example.com/mcp','',prefer_modern=False);session.phase='call';session.current_id=17;session.sse_resuming=True
        session.cancel_task_or_close=Mock();session.sse_resume_timer.start(1000);session.shutdown()
        session.cancel_task_or_close.assert_called_once_with(17);self.assertFalse(session.sse_resume_timer.isActive());self.assertFalse(session.sse_resuming)

    def test_remote_initialization_stream_resumes_with_original_session(self):
        import threading
        from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
        from PySide6.QtCore import QEventLoop,QTimer
        from PySide6.QtWidgets import QApplication
        from agentnik.mcp_remote import RemoteSession
        app=QApplication.instance() or QApplication([]);calls=[];state={};ping_received=threading.Event()
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def do_POST(self):
                body=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                if 'method' not in body:
                    calls.append(('ping-response',self.headers.get('Mcp-Session-Id'),body));self.send_response(202);self.end_headers();ping_received.set();return
                method=body['method'];calls.append(method)
                if method=='initialize':
                    state['id']=body['id'];self.send_response(200);self.send_header('Content-Type','text/event-stream');self.send_header('Mcp-Session-Id','session-one');self.end_headers();self.wfile.write(b'id: init-cursor\nretry: 20\ndata:\n\ndata: {"partial"');self.wfile.flush();return
                if method=='notifications/initialized':self.send_response(202);self.end_headers();return
                payload=json.dumps({'jsonrpc':'2.0','id':body['id'],'result':{'tools':[]}}).encode();self.send_response(200);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(payload)));self.end_headers();self.wfile.write(payload)
            def do_GET(self):
                cursor=self.headers.get('Last-Event-ID');calls.append(('GET',cursor,self.headers.get('Mcp-Session-Id'),self.headers.get('MCP-Protocol-Version'),self.headers.get('Authorization')))
                if not cursor:self.send_response(405);self.end_headers();return
                if not state.get('retried'):
                    state['retried']=True;self.send_response(503);self.end_headers();return
                result={'protocolVersion':PROTOCOL,'serverInfo':{'name':'Fixture','version':'1'},'capabilities':{'tools':{}}}
                payload=json.dumps({'jsonrpc':'2.0','id':state['id'],'result':result}).encode();self.send_response(200);self.send_header('Content-Type','text/event-stream');self.end_headers();self.wfile.write(b'id: ping\ndata: {"jsonrpc":"2.0","id":"ping-1","method":"ping"}\n\n');self.wfile.flush();ping_received.wait(3);self.wfile.write(b'id: init-result\ndata: '+payload+b'\n\n');self.wfile.flush()
            def do_DELETE(self):self.send_response(204);self.end_headers()
        server=ThreadingHTTPServer(('127.0.0.1',0),Handler);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        session=RemoteSession('http://127.0.0.1:'+str(server.server_port)+'/mcp','fixture-token',timeout_seconds=5,prefer_modern=False);loop=QEventLoop();out=[]
        session.discovered.connect(lambda result:(out.append(result),loop.quit()));session.ended.connect(lambda error:(out.append(error),loop.quit()));session.start();timeout=QTimer();timeout.setSingleShot(True);timeout.timeout.connect(loop.quit);timeout.start(7000)
        try:
            loop.exec();timeout.stop();self.assertTrue(out);self.assertEqual(out[0]['name'],'Fixture')
            self.assertEqual(calls.count('initialize'),1);self.assertEqual(calls.count(('GET','init-cursor','session-one',PROTOCOL,'Bearer fixture-token')),2);self.assertIn(('ping-response','session-one',{'jsonrpc':'2.0','id':'ping-1','result':{}}),calls);self.assertEqual(session.session,'session-one')
        finally:session.shutdown();server.shutdown();server.server_close();thread.join(2)

    def test_remote_tool_response_stream_resumes_without_repeating_call(self):
        import threading
        from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
        from PySide6.QtCore import QEventLoop,QTimer
        from PySide6.QtWidgets import QApplication
        from agentnik.mcp_remote import RemoteSession
        app=QApplication.instance() or QApplication([]);calls=[];state={};release=threading.Event()
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def do_POST(self):
                body=json.loads(self.rfile.read(int(self.headers['Content-Length'])));method=body['method'];calls.append(method)
                if method=='notifications/initialized':self.send_response(202);self.end_headers();return
                if method=='tools/call':
                    state['id']=body['id'];self.send_response(200);self.send_header('Content-Type','text/event-stream');self.end_headers();self.wfile.write(b'id: cursor-one\nretry: 20\ndata:\n\ndata: {"truncated"');self.wfile.flush();return
                result={'protocolVersion':PROTOCOL,'serverInfo':{'name':'Fixture','version':'1'},'capabilities':{'tools':{}}} if method=='initialize' else {'tools':[{'name':'work','inputSchema':{'type':'object'}}]}
                payload=json.dumps({'jsonrpc':'2.0','id':body['id'],'result':result}).encode();self.send_response(200);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(payload)));self.send_header('Mcp-Session-Id','session-one');self.end_headers();self.wfile.write(payload)
            def do_GET(self):
                cursor=self.headers.get('Last-Event-ID');calls.append(('GET',cursor,self.headers.get('Mcp-Session-Id'),self.headers.get('Authorization')))
                if not cursor:self.send_response(405);self.end_headers();return
                if not state.get('retried'):
                    state['retried']=True;self.send_response(503);self.end_headers();self.wfile.write(b'temporary error');return
                payload=json.dumps({'jsonrpc':'2.0','id':state['id'],'result':{'content':[{'type':'text','text':'finished'}]}}).encode()
                self.send_response(200);self.send_header('Content-Type','text/event-stream');self.end_headers();self.wfile.write(b'id: cursor-two\ndata: '+payload+b'\n\n');self.wfile.flush();release.wait(6)
            def do_DELETE(self):self.send_response(204);self.end_headers()
        server=ThreadingHTTPServer(('127.0.0.1',0),Handler);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        session=RemoteSession('http://127.0.0.1:'+str(server.server_port)+'/mcp','fixture-token',timeout_seconds=5,prefer_modern=False);loop=QEventLoop();out=[]
        session.discovered.connect(lambda info:session.call(info['tool_details'][0],{}));session.called.connect(lambda result:(out.append(result),loop.quit()));session.ended.connect(lambda error:(out.append(error),loop.quit()));session.start();timeout=QTimer();timeout.setSingleShot(True);timeout.timeout.connect(loop.quit);timeout.start(7000)
        try:
            loop.exec();timeout.stop();self.assertTrue(out);self.assertEqual(out[0]['call_result']['content'][0]['text'],'finished')
            self.assertEqual(calls.count('tools/call'),1);self.assertEqual(calls.count(('GET','cursor-one','session-one','Bearer fixture-token')),2)
        finally:release.set();session.shutdown();server.shutdown();server.server_close();thread.join(2)

    def test_remote_server_stream_reconnects_without_replaying_calls(self):
        import threading,time
        from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
        from PySide6.QtCore import QEventLoop,QTimer
        from PySide6.QtWidgets import QApplication
        from agentnik.mcp_remote import RemoteSession
        app=QApplication.instance() or QApplication([]);requests=[];ready=threading.Event();release=threading.Event()
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def do_POST(self):
                body=json.loads(self.rfile.read(int(self.headers['Content-Length'])));method=body['method'];requests.append(('POST',method))
                if method=='notifications/initialized':self.send_response(202);self.end_headers();return
                result={'protocolVersion':PROTOCOL,'serverInfo':{'name':'Fixture','version':'1'},'capabilities':{'tools':{},'resources':{}}} if method=='initialize' else {'tools':[]}
                payload=json.dumps({'jsonrpc':'2.0','id':body['id'],'result':result}).encode();self.send_response(200);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(payload)));self.send_header('Mcp-Session-Id','session-one');self.end_headers();self.wfile.write(payload)
            def do_GET(self):
                requests.append(('GET',self.headers.get('Last-Event-ID'),self.headers.get('Mcp-Session-Id'),self.headers.get('Authorization'),time.monotonic()));index=sum(r[0]=='GET' for r in requests)
                ready.wait(4);self.send_response(200);self.send_header('Content-Type','text/event-stream');self.end_headers()
                event=b'data: {"jsonrpc":"2.0","method":"notifications/resources/list_changed"}\n\n'
                try:
                    self.wfile.write(b'id: first\nretry: 25\n'+event);self.wfile.flush()
                    if index>1:self.wfile.write(b'id: second\n'+event);self.wfile.flush();release.wait(5)
                except OSError:pass
            def do_DELETE(self):release.set();self.send_response(204);self.end_headers()
        server=ThreadingHTTPServer(('127.0.0.1',0),Handler);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        session=RemoteSession('http://127.0.0.1:'+str(server.server_port)+'/mcp','fixture-token',timeout_seconds=5,prefer_modern=False);loop=QEventLoop();notices=[]
        def on_progress(message):
            notices.append(message)
            if sum('MCP resources changed' in x for x in notices)>=2:loop.quit()
        session.discovered.connect(lambda _:ready.set());session.progress.connect(on_progress);session.start();timeout=QTimer();timeout.setSingleShot(True);timeout.timeout.connect(loop.quit);timeout.start(6000)
        try:
            loop.exec();timeout.stop();gets=[r for r in requests if r[0]=='GET']
            self.assertEqual(len(gets),2);self.assertIsNone(gets[0][1]);self.assertEqual(gets[1][1:4],('first','session-one','Bearer fixture-token'));self.assertGreaterEqual(gets[1][4]-gets[0][4],0.9)
            self.assertEqual(sum('MCP resources changed' in x for x in notices),2);self.assertNotIn(('POST','tools/call'),requests)
        finally:release.set();session.shutdown();server.shutdown();server.server_close();thread.join(2)

    def test_remote_server_stream_resumption_tracks_complete_event_ids(self):
        from unittest.mock import Mock
        from PySide6.QtWidgets import QApplication
        from agentnik.mcp_remote import RemoteSession
        app=QApplication.instance() or QApplication([]);session=RemoteSession('https://example.com/mcp','fixture-token',prefer_modern=False);session.phase='call'
        notices=[];session.progress.connect(notices.append);reply=Mock();reply.attribute.return_value=200;reply.header.return_value='text/event-stream';session.server_stream=reply
        event=b'data: {"jsonrpc":"2.0","method":"notifications/resources/list_changed"}\n'
        reply.readAll.side_effect=[b'id: first\nretry: 2400\n'+event,b'\n',b'id: first\n'+event+b'\n',b'id: fixture-token\n'+event+b'\n']
        session.read_server_stream(reply);self.assertEqual(session.server_stream_last_id,b'');self.assertEqual(session.server_stream_retry_ms,2400)
        session.read_server_stream(reply);self.assertEqual(session.server_stream_last_id,b'first');self.assertEqual(len(notices),1)
        session.read_server_stream(reply);self.assertEqual(len(notices),1)
        session.read_server_stream(reply);self.assertEqual(session.server_stream_last_id,b'first');self.assertEqual(len(notices),2)
        session.server_stream=None;session.closed=True

    def test_remote_optional_server_stream_rejects_bad_content_and_is_bounded(self):
        from unittest.mock import Mock
        from PySide6.QtWidgets import QApplication
        from agentnik.mcp_remote import RemoteSession
        app=QApplication.instance() or QApplication([]);session=RemoteSession('https://example.com/mcp','',prefer_modern=False);session.phase='call';session.stop=Mock()
        for status,content_type,wire in ((405,'text/plain',b''),(200,'application/json',b'{}'),(200,'text/event-stream',b'data: '+b'x'*65537)):
            with self.subTest(status=status,content_type=content_type):
                reply=Mock();reply.attribute.return_value=status;reply.header.return_value=content_type;reply.readAll.return_value=wire;session.server_stream=reply
                session.read_server_stream(reply);self.assertIsNone(session.server_stream);reply.abort.assert_called_once()
        session.stop.assert_not_called();session.closed=True

    def test_local_stopped_tool_sends_cancellation_notification(self):
        from PySide6.QtCore import QEventLoop,QTimer
        from PySide6.QtWidgets import QApplication
        from agentnik.mcp_local import LocalSession
        app=QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as folder:
            server=Path(folder)/'cancel.py';marker=Path(folder)/'cancelled.json'
            server.write_text('''import json,sys
from pathlib import Path
for line in sys.stdin:
 req=json.loads(line);method=req['method']
 if method=='notifications/initialized':continue
 if method=='initialize':result={'protocolVersion':req['params']['protocolVersion'],'serverInfo':{'name':'Fake','version':'1'},'capabilities':{'tools':{}}}
 elif method=='tools/list':result={'tools':[{'name':'work','inputSchema':{'type':'object'}}]}
 elif method=='tools/call':
  token=req['params']['_meta']['progressToken'];print(json.dumps({'jsonrpc':'2.0','method':'notifications/progress','params':{'progressToken':token,'progress':1}}),flush=True);continue
 elif method=='notifications/cancelled':Path(sys.argv[1]).write_text(json.dumps(req['params']));break
 else:raise RuntimeError('unexpected '+method)
 print(json.dumps({'jsonrpc':'2.0','id':req['id'],'result':result}),flush=True)
''',encoding='utf-8')
            session=LocalSession(sys.executable,[str(server),str(marker)],prefer_modern=False);loop=QEventLoop();finished=[]
            session.discovered.connect(lambda info:session.call(info['tool_details'][0],{}))
            session.progress.connect(lambda detail:session.close() if detail.startswith('Progress') else None)
            session.shutdown_finished.connect(lambda value:(finished.append(value),loop.quit()))
            session.start();QTimer.singleShot(5000,loop.quit);loop.exec()
            self.assertTrue(finished);self.assertTrue(marker.exists());self.assertEqual(json.loads(marker.read_text())['requestId'],session.next_id)

    def test_catalog_notifications_invalidate_only_affected_state(self):
        from types import SimpleNamespace
        from agentnik.mcp_support import invalidate_server_list,MCPListChangedError
        session=SimpleNamespace(phase='call',resource_items=[{'uri':'a'}],template_items=[{'uriTemplate':'a'}],prompt_items=[{'name':'p'}],resource_links=[{'uri':'linked'}])
        self.assertIn('resources changed',invalidate_server_list(session,'notifications/resources/list_changed'))
        self.assertEqual(session.resource_items,[]);self.assertEqual(session.template_items,[]);self.assertEqual(session.resource_links,[{'uri':'linked'}]);self.assertEqual(session.prompt_items,[{'name':'p'}])
        self.assertIn('prompts changed',invalidate_server_list(session,'notifications/prompts/list_changed'));self.assertEqual(session.prompt_items,[])
        for phase,method in (('call','notifications/tools/list_changed'),('resource_list','notifications/resources/list_changed'),('template_list','notifications/resources/list_changed'),('prompt_list','notifications/prompts/list_changed'),('prompt_get','notifications/prompts/list_changed')):
            session.phase=phase
            with self.subTest(phase=phase),self.assertRaises(MCPListChangedError):invalidate_server_list(session,method)

    def test_local_catalog_updates_do_not_interrupt_unrelated_tool(self):
        from PySide6.QtCore import QEventLoop,QTimer
        from PySide6.QtWidgets import QApplication
        from agentnik.mcp_local import LocalSession
        app=QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as folder:
            server=Path(folder)/'catalog_change.py'
            server.write_text('''import json,sys
for line in sys.stdin:
 req=json.loads(line);method=req['method']
 if method=='notifications/initialized':continue
 if method=='initialize':result={'protocolVersion':req['params']['protocolVersion'],'serverInfo':{'name':'Fake','version':'1'},'capabilities':{'tools':{},'resources':{},'prompts':{}}}
 elif method=='tools/list':result={'tools':[{'name':'work','inputSchema':{'type':'object'}}]}
 elif method=='resources/list':result={'resources':[{'uri':'test://old','name':'old'}]}
 elif method=='prompts/list':result={'prompts':[{'name':'prompt'}]}
 elif method=='tools/call':
  for name in ('resources','prompts'):print(json.dumps({'jsonrpc':'2.0','method':'notifications/'+name+'/list_changed'}),flush=True)
  result={'content':[{'type':'text','text':'completed'}]}
 elif method=='resources/read':result={'contents':[{'uri':req['params']['uri'],'text':'fresh'}]}
 else:raise RuntimeError('unexpected '+method)
 print(json.dumps({'jsonrpc':'2.0','id':req['id'],'result':result}),flush=True)
''',encoding='utf-8')
            session=LocalSession(sys.executable,[str(server)],prefer_modern=False);loop=QEventLoop();out=[];notices=[];old=[]
            def resources(result):
                out.append(result)
                if len(out)==1:session.list_prompts()
                elif len(out)==3:self.assertTrue(session.read_resource('test://old'))
                else:loop.quit()
            def prompts(result):old.extend(result['prompts']);session.call(session.info['tool_details'][0],{})
            def called(result):
                out.append(result);self.assertFalse(session.read_resource('test://old'));self.assertFalse(session.list_prompts({'prompt':old[0],'arguments':{}}));self.assertTrue(session.list_resources())
            session.discovered.connect(lambda _:session.list_resources());session.resources.connect(resources);session.prompts.connect(prompts);session.called.connect(called);session.progress.connect(notices.append);session.ended.connect(lambda result:(out.append(result),loop.quit()));session.start();QTimer.singleShot(5000,loop.quit);loop.exec();session.close()
            self.assertEqual(out[1]['call_result']['content'][0]['text'],'completed');self.assertEqual(out[-1]['contents'][0]['text'],'fresh');self.assertEqual(len(notices),2)

    def test_remote_stream_catalog_updates_preserve_unrelated_result(self):
        from PySide6.QtWidgets import QApplication
        from agentnik.mcp_remote import RemoteSession,response_message
        from agentnik.mcp_support import MCPListChangedError
        app=QApplication.instance() or QApplication([]);session=RemoteSession('https://example.com/mcp','',prefer_modern=False);session.phase='call';session.resource_items=[{'uri':'old'}];session.template_items=[{'uriTemplate':'old'}];session.prompt_items=[{'name':'old'}];notices=[];session.progress.connect(notices.append)
        def frame(message):return b'data: '+json.dumps(message).encode()+b'\n\n'
        response={'jsonrpc':'2.0','id':7,'result':{'content':[]}}
        notifications=[{'jsonrpc':'2.0','method':'notifications/'+name+'/list_changed'} for name in ('resources','prompts')]
        self.assertEqual(response_message(b''.join(frame(x) for x in notifications+[response]),'text/event-stream',7,session.list_changed),response)
        self.assertEqual(session.resource_items,[]);self.assertEqual(session.template_items,[]);self.assertEqual(session.prompt_items,[]);self.assertEqual(len(notices),2)
        session.phase='prompt_get'
        with self.assertRaises(MCPListChangedError):response_message(frame(notifications[1])+frame(response),'text/event-stream',7,session.list_changed)
        session.closed=True

    def test_local_shutdown_attempts_task_cancellation_and_handles_result_race(self):
        from PySide6.QtCore import QEventLoop,QTimer
        from PySide6.QtWidgets import QApplication
        from agentnik.mcp_local import LocalSession
        app=QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as folder:
            server=Path(folder)/'local_cancel.py';marker=Path(folder)/'cancelled'
            server.write_text('''import json,sys,pathlib
mode=sys.argv[1];old_id=None
for line in sys.stdin:
 req=json.loads(line);method=req['method']
 if method=='notifications/initialized':continue
 if method=='initialize':
  tasks={'requests':{'tools':{'call':{}}}}
  if mode not in ('not-advertised','immediate-no-cancel'):tasks['cancel']={}
  result={'protocolVersion':req['params']['protocolVersion'],'serverInfo':{'name':'Fake','version':'1'},'capabilities':{'tools':{},'tasks':tasks}}
 elif method=='tools/list':result={'tools':[{'name':'work','inputSchema':{'type':'object'},'execution':{'taskSupport':'required'}}]}
 elif method=='tools/call':result={'task':{'taskId':'task-123','status':'working','createdAt':'2026-01-01T00:00:00Z','lastUpdatedAt':'2026-01-01T00:00:00Z','ttl':60000}}
 elif method=='tasks/result':pathlib.Path(sys.argv[2]+'.result').write_text('sent');old_id=req['id'];continue
 elif method=='tasks/cancel':
  pathlib.Path(sys.argv[2]).write_text(req['params']['taskId'])
  if mode=='timeout':continue
  if mode=='race':print(json.dumps({'jsonrpc':'2.0','id':old_id,'result':{'content':[],'_meta':{'io.modelcontextprotocol/related-task':{'taskId':'task-123'}}}}),flush=True)
  result={'taskId':'task-123','status':'working' if mode=='rejected' else 'cancelled'}
 else:raise RuntimeError('unexpected '+method)
 print(json.dumps({'jsonrpc':'2.0','id':req['id'],'result':result}),flush=True)
''',encoding='utf-8')
            for mode in ('confirmed','race','rejected','timeout','not-advertised','operation-timeout','immediate','immediate-no-cancel'):
                with self.subTest(mode=mode):
                    marker.unlink(missing_ok=True);result_marker=Path(str(marker)+'.result');result_marker.unlink(missing_ok=True);timeout=1 if mode=='operation-timeout' else 5
                    session=LocalSession(sys.executable,[str(server),mode,str(marker)],timeout_seconds=timeout,prefer_modern=False);loop=QEventLoop();finished=[];ended=[]
                    session.discovered.connect(lambda info:session.call(info['tool_details'][0],{}))
                    if mode in ('immediate','immediate-no-cancel'):session.progress.connect(lambda text:session.close() if text.startswith('Task started:') else None)
                    elif mode!='operation-timeout':session.progress.connect(lambda text:QTimer.singleShot(100,session.close) if text.startswith('Task started:') else None)
                    session.ended.connect(ended.append);session.shutdown_finished.connect(lambda value:(finished.append(value),loop.quit()));session.start();QTimer.singleShot(7000,loop.quit)
                    loop.exec();self.assertTrue(finished,mode);self.assertTrue(session.closed)
                    self.assertEqual(finished[0]['task_id'],'task-123')
                    if mode in ('not-advertised','immediate-no-cancel'):self.assertFalse(marker.exists());self.assertNotIn('task_cancelled',finished[0])
                    else:
                        self.assertEqual(marker.read_text(),'task-123');self.assertEqual(finished[0].get('task_cancelled'),mode in ('confirmed','race','operation-timeout','immediate'))
                    if mode in ('immediate','immediate-no-cancel'):self.assertFalse(result_marker.exists())
                    if mode=='operation-timeout':self.assertTrue(ended[0]['call_uncertain']);self.assertIn('task-123',ended[0]['error'])

    def test_remote_shutdown_cancels_active_task_when_advertised(self):
        import threading,time
        from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
        from PySide6.QtCore import QEventLoop,QTimer
        from PySide6.QtWidgets import QApplication
        from agentnik.mcp_remote import RemoteSession
        app=QApplication.instance() or QApplication([])
        for mode in ('confirmed','rejected','timeout','not-advertised','immediate','immediate-no-cancel'):
            with self.subTest(mode=mode):
                calls=[];release=threading.Event();result_started=threading.Event()
                class Handler(BaseHTTPRequestHandler):
                    def log_message(self,*args):pass
                    def do_POST(self):
                        req=json.loads(self.rfile.read(int(self.headers['Content-Length'])));method=req['method'];calls.append((method,self.headers.get('Mcp-Session-Id')))
                        if method=='notifications/initialized':self.send_response(202);self.end_headers();return
                        if method=='initialize':
                            tasks={'requests':{'tools':{'call':{}}}}
                            if mode not in ('not-advertised','immediate-no-cancel'):tasks['cancel']={}
                            result={'protocolVersion':PROTOCOL,'serverInfo':{'name':'Fake','version':'1'},'capabilities':{'tools':{},'tasks':tasks}}
                        elif method=='tools/list':result={'tools':[{'name':'work','inputSchema':{'type':'object'},'execution':{'taskSupport':'required'}}]}
                        elif method=='tools/call':result={'task':{'taskId':'task-123','status':'working','createdAt':'2026-01-01T00:00:00Z','lastUpdatedAt':'2026-01-01T00:00:00Z','ttl':60000}}
                        elif method=='tasks/result':result_started.set();release.wait(4);return
                        elif method=='tasks/cancel':
                            assert req['params']['taskId']=='task-123'
                            if mode=='timeout':time.sleep(4)
                            result={'taskId':'task-123','status':'cancelled' if mode in ('confirmed','immediate') else 'working'};release.set()
                        else:raise AssertionError(method)
                        payload=json.dumps({'jsonrpc':'2.0','id':req['id'],'result':result}).encode()
                        try:self.send_response(200);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(payload)));self.send_header('Mcp-Session-Id','session-one');self.end_headers();self.wfile.write(payload)
                        except OSError:pass
                    def do_DELETE(self):calls.append(('DELETE',self.headers.get('Mcp-Session-Id')));release.set();self.send_response(204);self.end_headers()
                server=ThreadingHTTPServer(('127.0.0.1',0),Handler);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
                session=RemoteSession('http://127.0.0.1:'+str(server.server_port)+'/mcp','',prefer_modern=False);loop=QEventLoop();finished=[]
                session.discovered.connect(lambda info:session.call(info['tool_details'][0],{}));session.finished.connect(lambda value:(finished.append(value),loop.quit()))
                if mode in ('immediate','immediate-no-cancel'):session.progress.connect(lambda text:session.shutdown() if text.startswith('Task started:') else None)
                timer=QTimer();timer.timeout.connect(lambda:session.shutdown() if result_started.is_set() else None);timer.start(10);session.start();QTimer.singleShot(7000,loop.quit)
                try:
                    loop.exec();timer.stop();self.assertTrue(finished,mode);self.assertEqual(finished[0]['task_id'],'task-123')
                    if mode in ('not-advertised','immediate-no-cancel'):self.assertNotIn('task_cancelled',finished[0]);self.assertNotIn('tasks/cancel',[item[0] for item in calls])
                    else:self.assertEqual(finished[0].get('task_cancelled'),mode in ('confirmed','immediate'));self.assertEqual([item[0] for item in calls].count('tasks/cancel'),1)
                    if mode in ('immediate','immediate-no-cancel'):self.assertNotIn('tasks/result',[item[0] for item in calls])
                    self.assertEqual([item[0] for item in calls].count('tools/call'),1);self.assertIn(('DELETE','session-one'),calls)
                finally:release.set();session.shutdown();server.shutdown();server.server_close();thread.join(2)

    def test_remote_stopped_tool_sends_cancellation_notification(self):
        import threading,time
        from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
        from PySide6.QtCore import QEventLoop,QTimer
        from PySide6.QtWidgets import QApplication
        from agentnik.mcp_remote import RemoteSession
        app=QApplication.instance() or QApplication([])
        for mode in ('accepted','rejected','notification-timeout','call-timeout'):
            with self.subTest(mode=mode):
                calls=[];started=threading.Event();release=threading.Event()
                class Handler(BaseHTTPRequestHandler):
                    def log_message(self,*args):pass
                    def do_POST(self):
                        mode_here=mode;release_here=release;started_here=started
                        req=json.loads(self.rfile.read(int(self.headers['Content-Length'])));method=req['method'];calls.append((method,req.get('id'),req.get('params'),self.headers.get('Mcp-Session-Id')))
                        if method=='notifications/initialized':self.send_response(202);self.end_headers();return
                        if method=='notifications/cancelled':
                            if mode_here=='notification-timeout':time.sleep(2)
                            release_here.set()
                            try:self.send_response(500 if mode_here=='rejected' else 202);self.end_headers()
                            except OSError:pass
                            return
                        if method=='initialize':result={'protocolVersion':PROTOCOL,'serverInfo':{'name':'Fake','version':'1'},'capabilities':{'tools':{}}}
                        elif method=='tools/list':result={'tools':[{'name':'work','inputSchema':{'type':'object'}}]}
                        elif method=='tools/call':
                            started_here.set();release_here.wait(4);result={'content':[{'type':'text','text':'late'}]}
                        else:raise AssertionError(method)
                        body=json.dumps({'jsonrpc':'2.0','id':req['id'],'result':result}).encode()
                        try:self.send_response(200);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(body)));self.send_header('Mcp-Session-Id','session-one');self.end_headers();self.wfile.write(body)
                        except OSError:pass
                    def do_DELETE(self):calls.append(('DELETE',None,None,self.headers.get('Mcp-Session-Id')));release.set();self.send_response(204);self.end_headers()
                server=ThreadingHTTPServer(('127.0.0.1',0),Handler);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
                session=RemoteSession('http://127.0.0.1:'+str(server.server_port)+'/mcp','',timeout_seconds=1 if mode=='call-timeout' else 5,prefer_modern=False);loop=QEventLoop();finished=[];ended=[];called=[]
                session.discovered.connect(lambda info:session.call(info['tool_details'][0],{}));session.called.connect(lambda value:called.append(value));session.ended.connect(lambda value:ended.append(value));session.finished.connect(lambda value:(finished.append(value),loop.quit()))
                timer=QTimer();timer.timeout.connect(lambda:session.shutdown() if mode!='call-timeout' and started.is_set() else None);timer.start(10);session.start();QTimer.singleShot(7000,loop.quit)
                try:
                    loop.exec();timer.stop();self.assertTrue(finished,(mode,calls,ended,session.phase));self.assertFalse(called)
                    call=next(item for item in calls if item[0]=='tools/call');cancel=next(item for item in calls if item[0]=='notifications/cancelled')
                    self.assertEqual(cancel[2],{'requestId':call[1]});self.assertEqual(cancel[3],'session-one');self.assertIn(('DELETE',None,None,'session-one'),calls)
                    self.assertEqual(sum(item[0]=='tools/call' for item in calls),1)
                    if mode=='call-timeout':self.assertTrue(ended[0]['call_uncertain'])
                finally:release.set();session.shutdown();server.shutdown();server.server_close();thread.join(2)

    def test_remote_task_required_tool_lifecycle_and_uncertain_failures(self):
        import threading,time
        from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
        from PySide6.QtCore import QEventLoop,QTimer
        from PySide6.QtWidgets import QApplication
        from agentnik.mcp_remote import RemoteSession
        app=QApplication.instance() or QApplication([])
        for mode in ('success','mismatch','timeout','no-capability'):
            with self.subTest(mode=mode):
                calls=[];state={}
                class Handler(BaseHTTPRequestHandler):
                    def log_message(self,*args):pass
                    def do_POST(self,state=state,mode=mode,calls=calls):
                        req=json.loads(self.rfile.read(int(self.headers['Content-Length'])));method=req['method'];calls.append((method,self.headers.get('Mcp-Session-Id')))
                        if method=='notifications/initialized':self.send_response(202);self.end_headers();return
                        if method=='initialize':
                            caps={'tools':{}}
                            if mode!='no-capability':caps['tasks']={'requests':{'tools':{'call':{}}}}
                            result={'protocolVersion':PROTOCOL,'serverInfo':{'name':'Fake','version':'1'},'capabilities':caps}
                        elif method=='tools/list':result={'tools':[{'name':'work','inputSchema':{'type':'object'},'execution':{'taskSupport':'required'}}]}
                        elif method=='tools/call':
                            assert req['params']['task']=={};state['token']=req['params']['_meta']['progressToken']
                            result={'task':{'taskId':'task-123','status':'working','createdAt':'2026-01-01T00:00:00Z','lastUpdatedAt':'2026-01-01T00:00:00Z','ttl':60000}}
                        elif method=='tasks/result':
                            assert req['params']['taskId']=='task-123'
                            if mode=='timeout':time.sleep(2)
                            result={'structuredContent':{'text':'task evidence'},'_meta':{'io.modelcontextprotocol/related-task':{'taskId':'different' if mode=='mismatch' else 'task-123'}}}
                            progress={'jsonrpc':'2.0','method':'notifications/progress','params':{'progressToken':state['token'],'progress':1,'total':2}}
                            status={'jsonrpc':'2.0','method':'notifications/tasks/status','params':{'taskId':'task-123','status':'input_required','statusMessage':'untrusted extra'}}
                            log={'jsonrpc':'2.0','method':'notifications/message','params':{'level':'warning','data':'Search is delayed'}}
                            payload=b'data: '+json.dumps(log).encode()+b'\n\ndata: '+json.dumps(status).encode()+b'\n\ndata: '+json.dumps(progress).encode()+b'\n\ndata: '+json.dumps({'jsonrpc':'2.0','id':req['id'],'result':result}).encode()+b'\n\n'
                            try:self.send_response(200);self.send_header('Content-Type','text/event-stream');self.send_header('Content-Length',str(len(payload)));self.end_headers();self.wfile.write(payload)
                            except (BrokenPipeError,ConnectionResetError,ConnectionAbortedError):pass
                            return
                        else:raise AssertionError(method)
                        payload=json.dumps({'jsonrpc':'2.0','id':req['id'],'result':result}).encode();self.send_response(200);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(payload)));self.send_header('Mcp-Session-Id','session-one');self.end_headers();self.wfile.write(payload)
                    def do_DELETE(self,calls=calls):calls.append(('DELETE',self.headers.get('Mcp-Session-Id')));self.send_response(204);self.end_headers()
                server=ThreadingHTTPServer(('127.0.0.1',0),Handler);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
                session=RemoteSession('http://127.0.0.1:'+str(server.server_port)+'/mcp','',timeout_seconds=1 if mode=='timeout' else 5,prefer_modern=False);loop=QEventLoop();out=[];notices=[]
                session.discovered.connect(lambda info:session.call(info['tool_details'][0],{}));session.progress.connect(notices.append);session.called.connect(lambda value:(out.append(value),loop.quit()));session.ended.connect(lambda value:(out.append(value),loop.quit()));session.start();QTimer.singleShot(7000,loop.quit)
                try:
                    loop.exec();session.shutdown();self.assertTrue(out,mode)
                    if mode=='success':self.assertEqual(out[0]['call_result']['structuredContent']['text'],'task evidence');self.assertEqual(out[0]['call_result']['content'],[]);self.assertTrue(any('input_required' in value for value in notices));self.assertTrue(any('Search is delayed' in value for value in notices));self.assertNotIn('untrusted extra',str(notices));self.assertTrue(any('Progress 1 / 2' in value for value in notices))
                    elif mode=='no-capability':self.assertFalse(out[0]['call_uncertain']);self.assertNotIn('tools/call',[item[0] for item in calls])
                    else:self.assertTrue(out[0]['call_uncertain']);self.assertIn('task-123',out[0]['error']);self.assertIn('may still be running',out[0]['error'])
                    self.assertLessEqual([item[0] for item in calls].count('tools/call'),1)
                    self.assertTrue(all(session_id=='session-one' for method,session_id in calls if method not in ('initialize',)))
                finally:session.shutdown();server.shutdown();server.server_close();thread.join(3)

    def test_local_task_required_tool_lifecycle_and_uncertain_failures(self):
        from PySide6.QtCore import QEventLoop,QTimer
        from PySide6.QtWidgets import QApplication
        from agentnik.mcp_local import LocalSession
        app=QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as folder:
            server=Path(folder)/'task_server.py'
            server.write_text('''import json,sys,time
mode=sys.argv[1]
for line in sys.stdin:
 req=json.loads(line);method=req['method']
 if method=='notifications/initialized':continue
 if method=='initialize':
  caps={'tools':{}}
  if mode!='no-capability':caps['tasks']={'requests':{'tools':{'call':{}}}}
  result={'protocolVersion':req['params']['protocolVersion'],'serverInfo':{'name':'Fake','version':'1'},'capabilities':caps}
 elif method=='tools/list':result={'tools':[{'name':'work','inputSchema':{'type':'object'},'execution':{'taskSupport':'required'}}]}
 elif method=='tools/call':
  assert req['params']['task']=={};token=req['params']['_meta']['progressToken']
  result={'task':{'taskId':'task-123','status':'working','createdAt':'2026-01-01T00:00:00Z','lastUpdatedAt':'2026-01-01T00:00:00Z','ttl':60000}}
 elif method=='tasks/result':
  assert req['params']['taskId']=='task-123'
  print(json.dumps({'jsonrpc':'2.0','method':'notifications/message','params':{'level':'warning','data':'Search is delayed'}}),flush=True)
  print(json.dumps({'jsonrpc':'2.0','method':'notifications/tasks/status','params':{'taskId':'task-123','status':'input_required','statusMessage':'untrusted extra'}}),flush=True)
  print(json.dumps({'jsonrpc':'2.0','method':'notifications/progress','params':{'progressToken':token,'progress':1,'total':2}}),flush=True)
  if mode=='timeout':time.sleep(2)
  result={'structuredContent':{'text':'task evidence'},'_meta':{'io.modelcontextprotocol/related-task':{'taskId':'different' if mode=='mismatch' else 'task-123'}}}
 else:raise RuntimeError('unexpected '+method)
 print(json.dumps({'jsonrpc':'2.0','id':req['id'],'result':result}),flush=True)
''',encoding='utf-8')
            for mode in ('success','mismatch','timeout','no-capability'):
                with self.subTest(mode=mode):
                    session=LocalSession(sys.executable,[str(server),mode],timeout_seconds=1 if mode=='timeout' else 5,prefer_modern=False);loop=QEventLoop();out=[];notices=[]
                    def discovered(info):
                        accepted=session.call(info['tool_details'][0],{})
                        if mode=='no-capability':out.append({'accepted':accepted});loop.quit()
                        else:self.assertTrue(accepted)
                    session.discovered.connect(discovered);session.progress.connect(notices.append);session.called.connect(lambda value:(out.append(value),loop.quit()));session.ended.connect(lambda value:(out.append(value),loop.quit()));session.start();QTimer.singleShot(7000,loop.quit);loop.exec();session.close()
                    self.assertTrue(out,mode)
                    if mode=='success':self.assertEqual(out[0]['call_result']['structuredContent']['text'],'task evidence');self.assertEqual(out[0]['call_result']['content'],[]);self.assertTrue(any('input_required' in value for value in notices));self.assertTrue(any('Search is delayed' in value for value in notices));self.assertNotIn('untrusted extra',str(notices));self.assertTrue(any('Progress 1 / 2' in value for value in notices))
                    elif mode=='no-capability':self.assertFalse(out[0]['accepted'])
                    else:self.assertTrue(out[0]['call_uncertain']);self.assertIn('task-123',out[0]['error']);self.assertIn('may still be running',out[0]['error'])

    def test_task_status_notice_filters_unrelated_and_duplicate_notifications(self):
        from agentnik.mcp_support import task_status_notice
        def msg(task,status):return {'jsonrpc':'2.0','method':'notifications/tasks/status','params':{'taskId':task,'status':status,'statusMessage':'untrusted'}}
        status,text=task_status_notice(msg('one','input_required'),'one','working')
        self.assertEqual(status,'input_required');self.assertIn('not supported',text);self.assertNotIn('untrusted',text)
        for value in (msg('other','completed'),msg('one','working'),msg('one','unknown'),dict(msg('one','failed'),id=1)):
            self.assertIsNone(task_status_notice(value,'one','working'))

    def test_server_log_notice_is_bounded_and_omits_structured_data(self):
        from agentnik.mcp_support import server_log_notice
        def msg(level,data):return {'method':'notifications/message','params':{'level':level,'data':data}}
        self.assertEqual(server_log_notice(msg('warning','bad\nnews')),'MCP server warning: bad news [untrusted server message]')
        self.assertNotIn('private-record',server_log_notice(msg('error',{'record':'private-record'})))
        self.assertLess(len(server_log_notice(msg('error','x'*5000))),300)
        self.assertIsNone(server_log_notice(msg('info','ignored')));self.assertIsNone(server_log_notice(dict(msg('error','bad'),id=1)))

    def test_progress_notice_requires_active_token_and_increasing_finite_values(self):
        from agentnik.mcp_support import progress_notice
        def msg(**params):return {'jsonrpc':'2.0','method':'notifications/progress','params':params}
        self.assertEqual(progress_notice(msg(progressToken='token',progress=2,total=4,message='Loading\n  charts'),'token',None),(2,'Progress 2 / 4: Loading charts'))
        for params in ({'progressToken':'other','progress':3},{'progressToken':'token','progress':1},{'progressToken':'token','progress':float('nan')},{'progressToken':'token','progress':10**400},{'progressToken':'token','progress':True},{'progressToken':'token','progress':3,'total':float('inf')},{'progressToken':'token','progress':3,'message':3}):
            with self.subTest(params=params):self.assertIsNone(progress_notice(msg(**params),'token',2))

    def test_local_tool_progress_reaches_worker_before_completion(self):
        import threading
        from PySide6.QtCore import QEventLoop,QTimer
        from PySide6.QtWidgets import QApplication
        from agentnik.mcp_code import CodingMCPBridge
        from agentnik.tools import Runtime
        app=QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as folder:
            server=Path(folder)/'progress_server.py'
            server.write_text('''import json,sys,time
for line in sys.stdin:
 req=json.loads(line);method=req['method']
 if method=='server/discover':print(json.dumps({'jsonrpc':'2.0','id':req['id'],'error':{'code':-32601,'message':'unsupported'}}),flush=True);continue
 if method=='notifications/initialized':continue
 if method=='initialize':result={'protocolVersion':req['params']['protocolVersion'],'serverInfo':{'name':'Fake','version':'1'},'capabilities':{'tools':{}}}
 elif method=='tools/list':result={'tools':[{'name':'long_job','inputSchema':{'type':'object'}}]}
 elif method=='tools/call':
  token=req['params']['_meta']['progressToken']
  for t in ('wrong',token):print(json.dumps({'jsonrpc':'2.0','method':'notifications/progress','params':{'progressToken':t,'progress':1,'total':4,'message':'Loading'}}),flush=True)
  time.sleep(.15);result={'content':[{'type':'text','text':'done'}]}
 else:raise RuntimeError('unexpected')
 print(json.dumps({'jsonrpc':'2.0','id':req['id'],'result':result}),flush=True)
''',encoding='utf-8')
            config={'mcp_servers':[{'name':'Local','command':sys.executable,'args':[str(server)],'enabled':True}]};bridge=CodingMCPBridge(config['mcp_servers'][0],config);runtime=Runtime();out=[]
            runtime.mcp_progress=lambda name,detail:out.append(('progress',name,detail)) if detail=='Progress 1 / 4: Loading' else None
            def work():
                info=bridge.request('discover',{},runtime);result=bridge.request('call',{'tool':info['tool_details'][0],'arguments':{}},runtime);out.append(('result',result));bridge.close_signal.emit()
            thread=threading.Thread(target=work);thread.start();loop=QEventLoop();timer=QTimer();timer.timeout.connect(lambda:loop.quit() if not thread.is_alive() else None);timer.start(10);QTimer.singleShot(5000,loop.quit);loop.exec();timer.stop();thread.join(1);bridge.close()
            self.assertFalse(thread.is_alive());self.assertEqual(out[0],('progress','Local','Progress 1 / 4: Loading'));self.assertEqual(out[1][0],'result');self.assertEqual(len(out),2)

    def test_remote_stream_progress_reaches_worker_before_response(self):
        import threading
        from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
        from PySide6.QtCore import QEventLoop,QTimer
        from PySide6.QtWidgets import QApplication
        from agentnik.mcp_code import CodingMCPBridge
        from agentnik.tools import Runtime
        progress_received=threading.Event();release=threading.Event();calls=[]
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def do_POST(self):
                req=json.loads(self.rfile.read(int(self.headers['Content-Length'])));method=req['method']
                if method=='server/discover':self.send_response(400);self.send_header('Content-Length','0');self.end_headers();return
                calls.append(method)
                if method=='notifications/initialized':self.send_response(202);self.end_headers();return
                if method=='initialize':result={'protocolVersion':PROTOCOL,'serverInfo':{'name':'Fake','version':'1'},'capabilities':{'tools':{}}}
                elif method=='tools/list':result={'tools':[{'name':'long_job','inputSchema':{'type':'object'}}]}
                elif method=='tools/call':
                    token=req['params']['_meta']['progressToken']
                    def progress(token,value):return b'data: '+json.dumps({'jsonrpc':'2.0','method':'notifications/progress','params':{'progressToken':token,'progress':value,'total':4,'message':'Loading'}}).encode()+b'\r\n\r\n'
                    before=progress('wrong',1)+progress(token,1);response=b'data: '+json.dumps({'jsonrpc':'2.0','id':req['id'],'result':{'content':[{'type':'text','text':'done'}]}}).encode()+b'\r\n\r\n';after=progress(token,2)
                    self.send_response(200);self.send_header('Content-Type','text/event-stream');self.send_header('Content-Length',str(len(before+response+after)));self.end_headers()
                    self.wfile.write(before[:-1]);self.wfile.flush();self.wfile.write(before[-1:]);self.wfile.flush();release.wait(3);self.wfile.write(response+after);self.wfile.flush();return
                else:raise AssertionError(method)
                body=json.dumps({'jsonrpc':'2.0','id':req['id'],'result':result}).encode();self.send_response(200);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body)
        app=QApplication.instance() or QApplication([]);server=ThreadingHTTPServer(('127.0.0.1',0),Handler);server_thread=threading.Thread(target=server.serve_forever,daemon=True);server_thread.start()
        config={'mcp_servers':[{'name':'Remote','transport':'http','url':'http://127.0.0.1:'+str(server.server_port)+'/mcp','credential_id':'','enabled':True}]};bridge=CodingMCPBridge(config['mcp_servers'][0],config);runtime=Runtime();out=[]
        def on_progress(name,detail):
            if detail=='Progress 1 / 4: Loading':out.append(('progress',name,detail));progress_received.set();release.set()
        runtime.mcp_progress=on_progress
        def work():
            info=bridge.request('discover',{},runtime);result=bridge.request('call',{'tool':info['tool_details'][0],'arguments':{}},runtime);out.append(('result',result));bridge.close_signal.emit()
        thread=threading.Thread(target=work);thread.start();loop=QEventLoop();timer=QTimer();timer.timeout.connect(lambda:loop.quit() if not thread.is_alive() else None);timer.start(10);QTimer.singleShot(5000,loop.quit)
        try:
            loop.exec();timer.stop();thread.join(1)
            self.assertTrue(progress_received.is_set());self.assertFalse(thread.is_alive());self.assertEqual(out[0],('progress','Remote','Progress 1 / 4: Loading'));self.assertEqual(out[1][0],'result');self.assertEqual(len(out),2)
            self.assertEqual(calls.count('tools/call'),1)
        finally:release.set();bridge.close();server.shutdown();server.server_close();server_thread.join(2)

    def test_parallel_mcp_documented_tool_selector_only(self):
        profile={'name':'Parallel','transport':'http','url':'https://mcp.parallel.ai/mcp?tools=web_search,web_research,find_verticals,search_vertical','credential_id':'','enabled':True}
        self.assertEqual(validate_servers([profile]),[profile])
        for url in ('https://mcp.parallel.ai/mcp?login','https://mcp.parallel.ai/mcp?tools=web_search&key=secret','https://mcp.parallel.ai/mcp?tools=web_search,web_search','https://mcp.parallel.ai/mcp?tools=unknown','https://evil.example/mcp?tools=web_search','https://mcp.parallel.ai/other?tools=web_search'):
            with self.subTest(url=url),self.assertRaises(ValueError):validate_servers([dict(profile,url=url)])
    def test_local_stdio_limit_applies_per_message_when_reads_are_coalesced(self):
        os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
        from PySide6.QtWidgets import QApplication
        from agentnik.mcp_local import LocalSession
        from agentnik.mcp_support import MAX_OUTPUT
        app=QApplication.instance() or QApplication([])
        session=LocalSession(sys.executable,[],prefer_modern=False);session.phase='call';session.next_id=7;results=[];ended=[]
        session.called.connect(results.append);session.ended.connect(ended.append)
        notification={'jsonrpc':'2.0','method':'notifications/message','params':{'data':'x'*40000}}
        reply={'jsonrpc':'2.0','id':7,'result':{'content':[{'type':'text','text':'y'*40000}]}}
        payload=(json.dumps(notification)+'\n'+json.dumps(reply)+'\n').encode()
        self.assertGreater(len(payload),MAX_OUTPUT)
        with patch.object(session.process,'readAllStandardOutput',return_value=payload):session.read()
        self.assertEqual(len(results),1);self.assertFalse(ended);self.assertFalse(session.closed);session.close()

    def test_local_stdio_rejects_one_oversized_complete_or_partial_message(self):
        os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
        from PySide6.QtWidgets import QApplication
        from agentnik.mcp_local import LocalSession
        from agentnik.mcp_support import MAX_TOOL_RESULT_OUTPUT
        app=QApplication.instance() or QApplication([])
        for complete in (False,True):
            with self.subTest(complete=complete):
                session=LocalSession(sys.executable,[],prefer_modern=False);session.phase='call';ended=[];session.ended.connect(ended.append)
                payload=b'x'*(MAX_TOOL_RESULT_OUTPUT+1)+(b'\n' if complete else b'')
                with patch.object(session.process,'readAllStandardOutput',return_value=payload):session.read()
                self.assertTrue(session.closed);self.assertEqual(len(ended),1);self.assertIn('output limit',ended[0]['error']);self.assertTrue(ended[0]['call_uncertain'])

    def test_large_tool_result_transport_limits(self):
        os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
        from PySide6.QtWidgets import QApplication
        from agentnik.mcp_local import LocalSession
        from agentnik.mcp_remote import RemoteProbe
        from agentnik.mcp_support import MAX_OUTPUT,MAX_TOOL_RESULT_OUTPUT
        app=QApplication.instance() or QApplication([])
        session=LocalSession(sys.executable,[],prefer_modern=False);session.phase='call';session.next_id=7;results=[];session.called.connect(results.append)
        payload=(json.dumps({'jsonrpc':'2.0','id':7,'result':{'content':[{'type':'text','text':'x'*1400000}]}})+'\n').encode()
        self.assertGreater(len(payload),MAX_OUTPUT);self.assertLess(len(payload),MAX_TOOL_RESULT_OUTPUT)
        with patch.object(session.process,'readAllStandardOutput',return_value=payload):session.read()
        self.assertEqual(len(results[0]['call_result']['content'][0]['text']),1400000);session.close()
        for phase,amount,rejected in [('call',1400000,False),('call',MAX_TOOL_RESULT_OUTPUT+1,True),('initialize',MAX_OUTPUT+1,True)]:
            with self.subTest(phase=phase,amount=amount):
                probe=RemoteProbe('http://127.0.0.1/','',prefer_modern=False);probe.phase=phase;probe.reply=unittest.mock.Mock();probe.reply.readAll.return_value=b'x'*amount
                with patch.object(probe,'stop') as stop:probe.consume();self.assertEqual(stop.called,rejected)

    def test_large_tool_image_survives_local_transport_and_validation(self):
        import base64
        from PySide6.QtWidgets import QApplication
        from test_image_generation import png
        from agentnik.mcp_local import LocalSession
        from agentnik.mcp_content import model_tool_result,model_images
        app=QApplication.instance() or QApplication([])
        data=png()+b'x'*(1024*1024);encoded=base64.b64encode(data).decode('ascii')
        session=LocalSession(sys.executable,[],prefer_modern=False);session.phase='call';session.next_id=7;results=[];session.called.connect(results.append)
        payload=(json.dumps({'jsonrpc':'2.0','id':7,'result':{'content':[{'type':'image','mimeType':'image/png','data':encoded}]}})+'\n').encode()
        with patch.object(session.process,'readAllStandardOutput',return_value=payload):session.read()
        visible,_,_=model_tool_result(results[0]['call_result']);sanitized,images=model_images(visible,True,1,'test')
        self.assertEqual(images[0][1],data);self.assertNotIn(encoded,json.dumps(sanitized));session.close()

    def test_local_discovery_accepts_large_page_and_enforces_128k(self):
        os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
        from PySide6.QtWidgets import QApplication
        from agentnik.mcp_local import LocalSession
        from agentnik.mcp_support import MAX_OUTPUT,MAX_DISCOVERY_OUTPUT
        app=QApplication.instance() or QApplication([])
        session=LocalSession(sys.executable,[],prefer_modern=False);session.phase='tools';session.next_id=2;session.pages=1;session.info={};results=[];session.discovered.connect(results.append)
        tools=[{'name':'tool'+str(i),'description':'x'*8000,'inputSchema':{'type':'object'}} for i in range(10)]
        payload=(json.dumps({'jsonrpc':'2.0','id':2,'result':{'tools':tools}})+'\n').encode()
        self.assertGreater(len(payload),MAX_OUTPUT);self.assertLessEqual(len(payload),MAX_DISCOVERY_OUTPUT)
        with patch.object(session.process,'readAllStandardOutput',return_value=payload):session.read()
        self.assertEqual(len(results[0]['tools']),10);self.assertFalse(session.closed);session.close()
        for complete in (False,True):
            with self.subTest(complete=complete):
                session=LocalSession(sys.executable,[],prefer_modern=False);session.phase='tools';ended=[];session.ended.connect(ended.append)
                with patch.object(session.process,'readAllStandardOutput',return_value=b'x'*(MAX_DISCOVERY_OUTPUT+1)+(b'\n' if complete else b'')):session.read()
                self.assertTrue(session.closed);self.assertIn('output limit',ended[0]['error'])

    def test_remote_discovery_accepts_large_page_and_enforces_128k(self):
        import threading
        from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
        os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
        from PySide6.QtCore import QEventLoop,QTimer
        from PySide6.QtWidgets import QApplication
        from agentnik.mcp_remote import RemoteProbe
        from agentnik.mcp_support import MAX_OUTPUT,MAX_DISCOVERY_OUTPUT
        class Handler(BaseHTTPRequestHandler):
            large=False
            def log_message(self,*args):pass
            def do_POST(self):
                body=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                if body['method']=='notifications/initialized':self.send_response(202);self.end_headers();return
                if body['method']=='initialize':result={'protocolVersion':PROTOCOL,'serverInfo':{'name':'Fake','version':'1'},'capabilities':{'tools':{}}}
                else:result={'tools':[{'name':'tool'+str(i),'description':'x'*8000,'inputSchema':{'type':'object'}} for i in range(17 if self.large else 10)]}
                payload=json.dumps({'jsonrpc':'2.0','id':body['id'],'result':result}).encode()
                if body['method']=='tools/list':
                    assert len(payload)>MAX_OUTPUT
                    assert (len(payload)>MAX_DISCOVERY_OUTPUT)==self.large
                self.send_response(200);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(payload)));self.end_headers()
                try:self.wfile.write(payload)
                except (BrokenPipeError,ConnectionResetError):pass
        app=QApplication.instance() or QApplication([]);server=ThreadingHTTPServer(('127.0.0.1',0),Handler);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        try:
            for too_large in (False,True):
                Handler.large=too_large;loop=QEventLoop();probe=RemoteProbe('http://127.0.0.1:'+str(server.server_port)+'/mcp','',prefer_modern=False);results=[]
                probe.finished.connect(lambda result:(results.append(result),loop.quit()));probe.start();QTimer.singleShot(5000,loop.quit);loop.exec()
                self.assertTrue(results)
                if too_large:self.assertIn('output limit',results[0]['error'])
                else:self.assertEqual(len(results[0]['tools']),10)
        finally:server.shutdown();server.server_close();thread.join(2)

    def test_tool_result_audiences_are_separated_without_mutation(self):
        from agentnik.mcp_content import model_tool_result
        content=[{'type':'text','text':'public'}, {'type':'text','text':'user-only','annotations':{'audience':['user']}},
                 {'type':'text','text':'model-only','annotations':{'audience':['assistant']}},
                 {'type':'text','text':'both','annotations':{'audience':['user','assistant']}},
                 {'type':'image','data':'user-binary','mimeType':'image/png','annotations':{'audience':['user']}},
                 {'type':'text','text':'neither','annotations':{'audience':[]}}]
        result={'content':content,'structuredContent':{'count':1},'isError':False};model,user,nontext=model_tool_result(result)
        self.assertEqual([x['text'] for x in model['content']],['public','model-only','both']);self.assertEqual(user,['user-only']);self.assertEqual(nontext,1)
        self.assertEqual(result['content'],content);self.assertEqual(model['structuredContent'],{'count':1})
        for invalid in (None,{},['user',3],['invalid'],'user'):
            with self.subTest(audience=invalid),self.assertRaises(ValueError):model_tool_result({'content':[{'type':'text','text':'x','annotations':{'audience':invalid}}]})
        for invalid in (None,[],{'audience':None}):
            with self.subTest(annotations=invalid),self.assertRaises(ValueError):model_tool_result({'content':[{'type':'text','text':'x','annotations':invalid}]})

    def test_structured_tool_output_schema_validation_and_definition_identity(self):
        from agentnik.mcp_schema import validate_tool_result
        from agentnik.mcp_remote import preview_tool
        output={'type':'object','properties':{'count':{'type':'integer','minimum':0}},'required':['count'],'additionalProperties':False}
        tool=preview_tool({'inputSchema':{'type':'object'},'outputSchema':output})
        self.assertEqual(tool['output_schema'],output);self.assertEqual(tool['output_schema_status'],'available')
        self.assertTrue(validate_tool_result(tool,{'content':[],'structuredContent':{'count':1}}))
        self.assertTrue(validate_tool_result(tool,{'content':[],'isError':True}))
        for result in ({'content':[]},{'content':[],'structuredContent':{'count':-1}},{'content':[],'structuredContent':[]}, {'content':[],'structuredContent':{'count':1,'extra':True}}):
            with self.subTest(result=result),self.assertRaises(ValueError):validate_tool_result(tool,result)
        changed=preview_tool({'inputSchema':{'type':'object'},'outputSchema':dict(output,required=[])})
        self.assertNotEqual(tool,changed)
        self.assertEqual(preview_tool({'inputSchema':{'type':'object'},'outputSchema':{'description':'x'*33000}})['output_schema_status'],'oversized')
        with self.assertRaises(ValueError):preview_tool({'outputSchema':[]})
        external=preview_tool({'inputSchema':{'type':'object'},'outputSchema':{'type':'object','$ref':'https://example.com/schema'}})
        with self.assertRaises(ValueError):validate_tool_result(external,{'structuredContent':{}})

    def test_parallel_advertised_output_schemas_validate_realistic_results(self):
        from agentnik.mcp_schema import validate_tool_result
        schemas=json.loads((Path(__file__).parent/'fixtures'/'parallel_mcp_output_schemas.json').read_text(encoding='utf-8'))
        fetch={'extract_id':'extract-test','results':[{'url':'https://example.com','excerpts':['Evidence'],'acquired_at':'2026-11-20T00:00:00Z'}],'errors':[],'session_id':'session-test'}
        research={'id':'response-test','output':[{'id':'search-test','action':{'type':'search'},'status':'completed','type':'web_search_call'}]}
        search={'search_id':'search-test','results':[],'session_id':'session-test'}
        for name,result in [('web_search',search),('web_fetch',fetch),('web_research',research)]:
            with self.subTest(tool=name):
                tool={'output_schema_status':'available','output_schema':schemas[name]}
                self.assertTrue(validate_tool_result(tool,{'content':[],'structuredContent':result}))
                with self.assertRaises(ValueError):validate_tool_result(tool,{'content':[],'structuredContent':{}})
        invalid={'id':'response-test','output':[{'id':'x','action':{'type':'unknown'},'status':'completed','type':'web_search_call'}]}
        with self.assertRaisesRegex(ValueError,'does not match'):validate_tool_result({'output_schema_status':'available','output_schema':schemas['web_research']},{'structuredContent':invalid})

    def test_schema_discriminator_is_bounded_metadata_without_external_refs(self):
        from agentnik.mcp_schema import validate_tool_arguments
        schema={'type':'object','$defs':{'item':{'type':'string'}},'properties':{'kind':{'$ref':'#/$defs/item','format':'date-time'}},'discriminator':{'propertyName':'kind','mapping':{'item':'#/$defs/item'}}}
        self.assertTrue(validate_tool_arguments(schema,{'kind':'not-a-date'})) # format is an annotation under JSON Schema's default vocabulary.
        for discriminator in ({'propertyName':'kind','mapping':{'item':'https://example.com/schema'}},{'propertyName':'kind','mapping':{'item':'#/$defs/missing'}},{'propertyName':7},{'propertyName':'kind','extra':True}):
            with self.subTest(discriminator=discriminator),self.assertRaises(ValueError):validate_tool_arguments(dict(schema,discriminator=discriminator),{'kind':'x'})
        with self.assertRaises(ValueError):validate_tool_arguments({'type':'object','properties':{'x':{'type':'string','format':[]}}},{'x':'x'})

    def test_argument_schema_validation_and_unsupported_features(self):
        from agentnik.mcp_schema import validate_tool_arguments
        schema={'type':'object','properties':{'query':{'type':'string'},'n':{'type':'integer','minimum':1}},'required':['query'],'additionalProperties':False}
        self.assertTrue(validate_tool_arguments(schema,{'query':'MCP','n':2}))
        for arguments in ({},{'query':3},{'query':'ok','n':0},{'query':'ok','extra':True}):
            with self.subTest(arguments=arguments),self.assertRaisesRegex(ValueError,'do not match'):validate_tool_arguments(schema,arguments)
        self.assertTrue(validate_tool_arguments({'type':'object','properties':{'database':{'anyOf':[{'type':'string'},{'type':'null'}]}}},{'database':None}))
        for unsafe in ({'type':'object','$ref':'https://example.com/schema'},):
            with self.subTest(schema=unsafe),self.assertRaisesRegex(ValueError,'unsupported'):validate_tool_arguments(unsafe,{})

    def test_schema_boolean_and_tuple_subschemas(self):
        from agentnik.mcp_schema import validate_tool_arguments,validate_tool_result
        for dialect,tuple_schema in (('https://json-schema.org/draft/2020-12/schema',{'prefixItems':[{'type':'string'},{'type':'integer'}],'items':False}),('http://json-schema.org/draft-07/schema#',{'items':[{'type':'string'},{'type':'integer'}],'additionalItems':False})):
            schema={'$schema':dialect,'type':'object','$defs':{'allow':True,'deny':False},'properties':{'pair':dict(type='array',minItems=2,**tuple_schema),'anything':{'$ref':'#/$defs/allow'},'forbidden':{'$ref':'#/$defs/deny'}},'required':['pair']}
            with self.subTest(dialect=dialect):
                self.assertTrue(validate_tool_arguments(schema,{'pair':['x',2],'anything':{'a':1}}))
                for invalid in ({'pair':['x',2,3]},{'pair':['x','2']},{'pair':['x',2],'forbidden':None}):
                    with self.assertRaisesRegex(ValueError,'do not match'):validate_tool_arguments(schema,invalid)
                tool={'output_schema_status':'available','output_schema':schema}
                self.assertTrue(validate_tool_result(tool,{'structuredContent':{'pair':['x',2]}}))
                with self.assertRaisesRegex(ValueError,'does not match'):validate_tool_result(tool,{'structuredContent':{'pair':['x',2,3]}})
        for invalid in ({'type':'object','properties':{'x':{'prefixItems':[True]}} ,'$schema':'http://json-schema.org/draft-07/schema#'}, {'type':'object','properties':{'x':{'items':[True]}}}, {'type':'object','properties':{'x':{'prefixItems':[True]*129}}}):
            with self.subTest(schema=invalid),self.assertRaises(ValueError):validate_tool_arguments(invalid,{})
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

    def test_schema_allows_large_flat_titled_choices_but_bounds_complex_branches(self):
        from agentnik.mcp_schema import validate_tool_arguments,MCPArgumentValidationError
        choices=[{'const':'v'+str(i),'title':'Choice '+str(i)} for i in range(20)]
        schema={'type':'object','properties':{'single':{'type':'string','oneOf':choices},'multiple':{'type':'array','items':{'anyOf':choices}}}}
        self.assertTrue(validate_tool_arguments(schema,{'single':'v19','multiple':['v2','v15']}))
        with self.assertRaises(MCPArgumentValidationError):validate_tool_arguments(schema,{'single':'missing'})
        duplicate=choices+[{'const':'v2','title':'Duplicate'}]
        one_of={'type':'object','properties':{'x':{'oneOf':duplicate}}};any_of={'type':'object','properties':{'x':{'anyOf':duplicate}}}
        with self.assertRaises(MCPArgumentValidationError):validate_tool_arguments(one_of,{'x':'v2'})
        self.assertTrue(validate_tool_arguments(any_of,{'x':'v2'}))
        too_many={'type':'object','properties':{'x':{'oneOf':[{'const':str(i)} for i in range(129)]}}}
        with self.assertRaises(ValueError):validate_tool_arguments(too_many,{})
        complex_choices={'type':'object','properties':{'x':{'oneOf':[{'type':'string','pattern':str(i)} for i in range(9)]}}}
        with self.assertRaises(ValueError):validate_tool_arguments(complex_choices,{})

    def test_schema_legacy_definitions_and_cross_namespace_cycles(self):
        from agentnik.mcp_schema import validate_tool_arguments
        schema={'type':'object','definitions':{'key/name':{'type':'integer','minimum':1},'alias':{'$ref':'#/$defs/target'}},'$defs':{'target':{'$ref':'#/definitions/key~1name'}},'properties':{'id':{'$ref':'#/definitions/alias'}},'required':['id']}
        self.assertTrue(validate_tool_arguments(schema,{'id':2}))
        with self.assertRaisesRegex(ValueError,'do not match'):validate_tool_arguments(schema,{'id':0})
        cycle={'type':'object','definitions':{'x':{'$ref':'#/$defs/y'}},'$defs':{'y':{'$ref':'#/definitions/x'}}}
        with self.assertRaisesRegex(ValueError,'recursive'):validate_tool_arguments(cycle,{})
        self.assertTrue(validate_tool_arguments({'type':'object','definitions':{'patterns':{'patternProperties':{'x':{}}}}},{}))
        for invalid in ({'type':'object','properties':{'x':{'definitions':{'y':{'type':'string'}}}}}, {'type':'object','definitions':{str(i):{} for i in range(129)}}, {'type':'object','definitions':{'a':{}},'properties':{'x':{'$ref':'#/definitions/a/extra'}}}):
            with self.subTest(invalid=invalid),self.assertRaises(ValueError):validate_tool_arguments(invalid,{})

    def test_schema_references_to_nested_subschemas(self):
        from agentnik.mcp_schema import validate_tool_arguments,validate_tool_result
        schema={'type':'object','$defs':{'record':{'type':'object','properties':{'a/b':{'type':'integer','minimum':2},'pair':{'type':'array','prefixItems':[{'type':'string'},{'type':'integer'}]}}}},'properties':{'value':{'$ref':'#/$defs/record/properties/a~1b'},'word':{'$ref':'#/$defs/record/properties/pair/prefixItems/0'},'duplicate':{'$ref':'#/properties/value'}},'required':['value','word','duplicate']}
        valid={'value':2,'word':'ok','duplicate':3}
        self.assertTrue(validate_tool_arguments(schema,valid))
        with self.assertRaisesRegex(ValueError,'do not match'):validate_tool_arguments(schema,dict(valid,duplicate=1))
        self.assertTrue(validate_tool_result({'output_schema_status':'available','output_schema':schema},{'structuredContent':valid}))
        cycle={'type':'object','properties':{'a':{'$ref':'#/properties/b'},'b':{'$ref':'#/properties/a'}}}
        with self.assertRaisesRegex(ValueError,'recursive'):validate_tool_arguments(cycle,{})
        for ref in ('#/properties/value/description','#/$defs/record/properties/pair/prefixItems/00','#/$defs/record/properties/pair/prefixItems/2','#/properties/value/$ref'):
            bad=dict(schema,properties={'bad':{'$ref':ref},**schema['properties']})
            with self.subTest(ref=ref),self.assertRaises(ValueError):validate_tool_arguments(bad,valid)

    def test_schema_mismatch_feedback_omits_argument_values(self):
        from agentnik.mcp_schema import validate_tool_arguments,MCPArgumentValidationError
        schema={'type':'object','properties':{'profile':{'type':'object','properties':{'age':{'type':'integer'}},'required':['age']}},'required':['profile']}
        with self.assertRaises(MCPArgumentValidationError) as missing:validate_tool_arguments(schema,{'profile':{}})
        self.assertIn('profile.age',str(missing.exception));self.assertIn('required',str(missing.exception))
        with self.assertRaises(MCPArgumentValidationError) as wrong:validate_tool_arguments(schema,{'profile':{'age':'private-value'}})
        self.assertIn('profile.age',str(wrong.exception));self.assertIn('wrong type',str(wrong.exception));self.assertNotIn('private-value',str(wrong.exception))

    def test_draft7_tool_schema_uses_declared_dialect_and_bounded_references(self):
        from agentnik.mcp_schema import validate_tool_arguments
        for uri in ('http://json-schema.org/draft-07/schema#','https://json-schema.org/draft-07/schema'):
            with self.subTest(uri=uri):
                schema={'$schema':uri,'type':'object','definitions':{'item':{'type':'integer','minimum':1}},'properties':{'id':{'$ref':'#/definitions/item','maximum':2}},'required':['id']}
                self.assertTrue(validate_tool_arguments(schema,{'id':3})) # Draft 7 ignores $ref siblings.
                with self.assertRaisesRegex(ValueError,'do not match'):validate_tool_arguments(schema,{'id':0})
                with self.assertRaisesRegex(ValueError,'do not match'):validate_tool_arguments(schema,{})
        schema['$schema']='https://json-schema.org/draft/2020-12/schema'
        with self.assertRaisesRegex(ValueError,'do not match'):validate_tool_arguments(schema,{'id':3})
        for invalid in ({'$schema':'http://json-schema.org/draft-04/schema#','type':'object'}, {'$schema':'http://json-schema.org/draft-07/schema#','type':'object','properties':{'x':{'$schema':'http://json-schema.org/draft-07/schema#'}}}, {'$schema':'http://json-schema.org/draft-07/schema#','type':'object','definitions':{'x':{'$ref':'#/definitions/x'}}}):
            with self.subTest(schema=invalid),self.assertRaises(ValueError):validate_tool_arguments(invalid,{})

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

    def test_server_timeout_validation_and_legacy_defaults(self):
        from agentnik.mcp_support import server_timeout,server_fingerprint
        local={'name':'Local','command':sys.executable,'args':[],'enabled':True}
        remote={'name':'Remote','transport':'http','url':'https://example.com/mcp','credential_id':'','enabled':True}
        for item in (local,remote):
            self.assertEqual(server_timeout(item),60)
            self.assertEqual(server_timeout(dict(item,timeout_seconds=300)),300)
            self.assertNotEqual(server_fingerprint(item),server_fingerprint(dict(item,timeout_seconds=300)))
            for value in (0,901,True,1.5,'60',None):
                with self.subTest(value=value),self.assertRaises(ValueError):validate_servers([dict(item,timeout_seconds=value)])

    def test_working_directory_configuration_is_absolute_and_fingerprinted(self):
        from agentnik.mcp_support import server_fingerprint
        item={'name':'Local','command':sys.executable,'args':[],'enabled':True}
        with tempfile.TemporaryDirectory() as directory:
            changed=dict(item,working_directory=directory);validate_servers([changed])
            self.assertNotEqual(server_fingerprint(item),server_fingerprint(changed))
            with tempfile.TemporaryDirectory() as data:
                store=Store(data)
                try:store.config['mcp_servers']=[changed];store.flush();self.assertEqual(load_config(store.config_path)['mcp_servers'],[changed])
                finally:store.db.close()
        for value in ('relative/path','../folder','C:relative',3,'x\x00y'):
            with self.subTest(value=value),self.assertRaises(ValueError):validate_servers([dict(item,working_directory=value)])
        remote={'name':'Remote','transport':'http','url':'https://example.com/mcp','credential_id':'','enabled':True,'working_directory':'/tmp'}
        with self.assertRaises(ValueError):validate_servers([remote])

    def test_local_server_launches_in_configured_working_directory(self):
        os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
        from PySide6.QtCore import QEventLoop,QTimer
        from PySide6.QtWidgets import QApplication
        from agentnik.mcp_local import LocalSession
        app=QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);work=root/'server-work';work.mkdir();server=root/'server.py'
            server.write_text('''import json,os,sys
for line in sys.stdin:
 req=json.loads(line)
 if req['method']=='initialize':
  result={'protocolVersion':req['params']['protocolVersion'],'serverInfo':{'name':os.getcwd(),'version':'1'},'capabilities':{}}
  print(json.dumps({'jsonrpc':'2.0','id':req['id'],'result':result}),flush=True)
''',encoding='utf-8')
            session=LocalSession(sys.executable,[str(server)],working_directory=str(work),prefer_modern=False);loop=QEventLoop();out=[]
            session.discovered.connect(lambda result:(out.append(result),loop.quit()));session.ended.connect(lambda result:(out.append(result),loop.quit()))
            session.start();QTimer.singleShot(5000,loop.quit);loop.exec();session.close()
            self.assertEqual(Path(out[0]['name']).resolve(),work.resolve())
        with self.assertRaises(ValueError):LocalSession(sys.executable,[],working_directory='relative',prefer_modern=False)

    def test_local_and_remote_operation_timers_use_configured_timeout(self):
        os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
        from PySide6.QtWidgets import QApplication
        from agentnik.mcp_local import LocalSession
        from agentnik.mcp_remote import RemoteProbe,RemoteSession
        app=QApplication.instance() or QApplication([])
        local=LocalSession(sys.executable,[],timeout_seconds=180,prefer_modern=False);local.phase='ready'
        tool={'name':'test','schema_status':'available','task_support':'forbidden'};local.details=[tool]
        try:
            with patch.object(local,'list_page'):
                self.assertTrue(local.call(tool,{}));self.assertEqual(local.timer.interval(),180000)
            local.timer.stop()
            remote=RemoteSession('https://example.com/mcp','',timeout_seconds=240,prefer_modern=False);remote.phase='ready'
            with patch.object(remote,'send'):
                self.assertTrue(remote.call(tool,{}));self.assertEqual(remote.timer.interval(),240000)
            remote.timer.stop()
            probe=RemoteProbe('https://example.com/mcp','',timeout_seconds=120,prefer_modern=False)
            with patch.object(probe,'send'):
                probe.start();self.assertEqual(probe.timer.interval(),120000)
            probe.timer.stop()
        finally:local.close();app.processEvents()

    def test_manager_saves_and_loads_per_server_timeout(self):
        os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
        from PySide6.QtWidgets import QApplication,QFileDialog
        from agentnik.ui import Window
        from agentnik.mcp_ui import MCPServers
        app=QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as folder,patch('agentnik.core.discover',return_value={}),patch('agentnik.core.environment_connections',return_value={}):
            store=Store(folder);window=Window(store);dialog=MCPServers(window)
            try:
                dialog.new();dialog.name.setText('Local');dialog.command.setText(sys.executable);dialog.timeout.setValue(300)
                with patch.object(QFileDialog,'getExistingDirectory',return_value=folder):dialog.working_directory_button.click()
                self.assertEqual(dialog.working_directory.text(),folder);dialog.save()
                self.assertEqual(store.config['mcp_servers'][0]['timeout_seconds'],300)
                self.assertEqual(store.config['mcp_servers'][0]['working_directory'],folder)
                dialog.timeout.setValue(1);dialog.load_row(0);self.assertEqual(dialog.timeout.value(),300)
                self.assertEqual(dialog.working_directory.text(),folder)
                self.assertEqual(load_config(store.config_path)['mcp_servers'][0]['timeout_seconds'],300)
            finally:dialog.close();window.close();app.processEvents();store.db.close()

    def test_manager_fits_small_window_and_scrolls_to_controls(self):
        os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
        from PySide6.QtWidgets import QApplication,QScrollArea
        from agentnik.ui import Window
        from agentnik.mcp_ui import MCPServers
        app=QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as folder,patch('agentnik.core.discover',return_value={}),patch('agentnik.core.environment_connections',return_value={}):
            store=Store(folder);window=Window(store);dialog=MCPServers(window)
            try:
                dialog.resize(520,400);dialog.show();app.processEvents()
                scroll=dialog.findChild(QScrollArea,'mcpSettingsScroll')
                self.assertLessEqual(dialog.height(),400);self.assertGreater(scroll.verticalScrollBar().maximum(),0)
                scroll.ensureWidgetVisible(dialog.tool_result);app.processEvents()
                self.assertGreater(scroll.verticalScrollBar().value(),0)
            finally:dialog.close();window.close();app.processEvents();store.db.close()

    @unittest.skipUnless(os.name=='nt','Windows job-object behavior')
    def test_local_mcp_shutdown_terminates_owned_descendant(self):
        os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
        from PySide6.QtCore import QEventLoop,QTimer
        from PySide6.QtWidgets import QApplication
        from agentnik.mcp_local import LocalSession
        app=QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as folder:
            server=Path(folder)/'server.py';child=Path(folder)/'child.py';marker=Path(folder)/'child-finished'
            child.write_text('import pathlib,sys,time\ntime.sleep(1.5)\npathlib.Path(sys.argv[1]).write_text("survived")\n',encoding='utf-8')
            server.write_text('''import json,subprocess,sys
for line in sys.stdin:
 req=json.loads(line)
 if req['method']=='initialize':
  subprocess.Popen([sys.executable,sys.argv[1],sys.argv[2]],stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,creationflags=subprocess.CREATE_NO_WINDOW)
  result={'protocolVersion':req['params']['protocolVersion'],'serverInfo':{'name':'Parent','version':'1'},'capabilities':{}}
  print(json.dumps({'jsonrpc':'2.0','id':req['id'],'result':result}),flush=True)
''',encoding='utf-8')
            session=LocalSession(sys.executable,[str(server),str(child),str(marker)],prefer_modern=False);loop=QEventLoop();out=[]
            session.discovered.connect(lambda info:(out.append(info),loop.quit()));session.ended.connect(lambda error:(out.append(error),loop.quit()));session.start();QTimer.singleShot(5000,loop.quit);loop.exec()
            self.assertEqual(out[0]['name'],'Parent');session.close()
            wait=QEventLoop();QTimer.singleShot(2000,wait.quit);wait.exec();self.assertFalse(marker.exists(),'Owned descendant continued after session shutdown')

    @unittest.skipUnless(os.name=='nt','Windows job-object behavior')
    def test_local_mcp_job_assignment_failure_does_not_initialize(self):
        os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
        from PySide6.QtCore import QEventLoop,QTimer
        from PySide6.QtWidgets import QApplication
        from agentnik.mcp_local import LocalSession
        app=QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as folder:
            marker=Path(folder)/'received';server=Path(folder)/'server.py'
            server.write_text('import pathlib,sys\nline=sys.stdin.readline()\nif line:pathlib.Path(sys.argv[1]).write_text("received")\n',encoding='utf-8')
            with patch('agentnik.shell.WindowsJob') as job:
                job.return_value.assign_pid.side_effect=OSError('fixture');session=LocalSession(sys.executable,[str(server),str(marker)],prefer_modern=False);loop=QEventLoop();out=[]
                session.ended.connect(lambda result:(out.append(result),loop.quit()));session.start();QTimer.singleShot(5000,loop.quit);loop.exec();session.close()
                self.assertIn('isolate',out[0]['error']);self.assertFalse(marker.exists());job.return_value.close.assert_called_once()

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
            session=LocalSession(sys.executable,[str(server)],env_refs={'TARGET_TOKEN':'AGENTNIK_TEST_MCP_TOKEN'},prefer_modern=False);loop=QEventLoop();results=[]
            def discovered(info):results.append(info);session.call(info['tool_details'][0],{})
            session.discovered.connect(discovered);session.ended.connect(lambda result:(results.append(result),loop.quit()));session.start();QTimer.singleShot(5000,loop.quit);loop.exec();session.close()
            self.assertEqual(results[0]['name'],'mapped');self.assertIn('mapped environment value',results[1]['error']);self.assertTrue(results[1]['call_uncertain']);self.assertNotIn('secret-fixture-value',str(results))

    def test_local_server_ping_and_unsupported_request_during_operations(self):
        os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
        from PySide6.QtCore import QEventLoop,QTimer
        from PySide6.QtWidgets import QApplication
        from agentnik.mcp_local import LocalSession
        app=QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as folder:
            server=Path(folder)/'ping.py'
            server.write_text('''import json,sys

def send(message):print(json.dumps(message),flush=True)
def ask(method,ident):
 send({'jsonrpc':'2.0','id':ident,'method':method})
 answer=json.loads(sys.stdin.readline())
 assert answer['id']==ident
 if method=='ping':assert answer.get('result')=={}
 else:assert answer.get('error',{}).get('code')==-32601
for line in sys.stdin:
 req=json.loads(line);method=req['method']
 if method=='notifications/initialized':continue
 if method=='initialize':
  ask('ping',req['id']);result={'protocolVersion':req['params']['protocolVersion'],'serverInfo':{'name':'Fake','version':'1'},'capabilities':{'tools':{}}}
 elif method=='tools/list':
  ask('roots/list','server-request');result={'tools':[{'name':'echo','inputSchema':{'type':'object'}}]}
 elif method=='tools/call':
  ask('ping','heartbeat');result={'content':[{'type':'text','text':'ok'}]}
 else:raise RuntimeError('unexpected')
 send({'jsonrpc':'2.0','id':req['id'],'result':result})
''',encoding='utf-8')
            session=LocalSession(sys.executable,[str(server)],prefer_modern=False);loop=QEventLoop();results=[]
            session.discovered.connect(lambda info:(results.append(info),session.call(info['tool_details'][0],{})))
            session.called.connect(lambda result:(results.append(result),loop.quit()));session.ended.connect(lambda result:(results.append(result),loop.quit()))
            session.start();QTimer.singleShot(5000,loop.quit);loop.exec();session.close()
            self.assertEqual(results[0]['name'],'Fake');self.assertEqual(results[1]['call_result']['content'][0]['text'],'ok')

    def test_local_server_request_flood_is_bounded(self):
        os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
        from PySide6.QtCore import QEventLoop,QTimer
        from PySide6.QtWidgets import QApplication
        from agentnik.mcp_local import LocalSession
        app=QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as folder:
            server=Path(folder)/'flood.py';server.write_text('''import json,sys
sys.stdin.readline()
for n in range(33):print(json.dumps({'jsonrpc':'2.0','id':n,'method':'ping'}),flush=True)
sys.stdin.read()
''',encoding='utf-8')
            session=LocalSession(sys.executable,[str(server)],prefer_modern=False);loop=QEventLoop();results=[]
            session.ended.connect(lambda result:(results.append(result),loop.quit()));session.start();QTimer.singleShot(5000,loop.quit);loop.exec();session.close()
            self.assertIn('error',results[0]);self.assertEqual(len(session.server_requests),32)

    def test_protocol_response_validation(self):
        result={'jsonrpc':'2.0','id':1,'result':{'protocolVersion':PROTOCOL,'serverInfo':{'name':'Example','version':'1'},'capabilities':{'tools':{},'resources':{}}}}
        self.assertEqual(parse_initialize(json.dumps(result).encode())['capabilities'],['tools','resources'])
        older=dict(result,result=dict(result['result'],protocolVersion='2024-11-05'))
        self.assertEqual(parse_initialize(json.dumps(older).encode(),(PROTOCOL,'2024-11-05'))['protocol'],'2024-11-05')
        for message in (b'not json',json.dumps(dict(result,id=True)).encode(),json.dumps(dict(result,result={'protocolVersion':'different'})).encode()):
            with self.assertRaises(ValueError):parse_initialize(message)

    def test_task_capabilities_are_reported_only_for_supported_protocol_and_shapes(self):
        result={'jsonrpc':'2.0','id':1,'result':{'protocolVersion':PROTOCOL,'serverInfo':{'name':'Example','version':'1'},'capabilities':{'tools':{},'tasks':{'list':{},'cancel':{},'requests':{'tools':{'call':{}}}}}}}
        parsed=parse_initialize(json.dumps(result).encode())
        self.assertIn('tasks',parsed['capabilities']);self.assertEqual(parsed['task_capabilities'],{'tool_calls':True,'list':True,'cancel':True})
        result['result']['capabilities']['tasks']={'list':True,'cancel':None,'requests':{'tools':{'call':True}}}
        parsed=parse_initialize(json.dumps(result).encode());self.assertEqual(parsed['task_capabilities'],{'tool_calls':False,'list':False,'cancel':False})
        result['result']['protocolVersion']='2025-06-18';result['result']['capabilities']['tasks']={'requests':{'tools':{'call':{}}}}
        parsed=parse_initialize(json.dumps(result).encode(),(PROTOCOL,'2025-06-18'));self.assertNotIn('tasks',parsed['capabilities']);self.assertFalse(parsed['task_capabilities']['tool_calls'])

    def test_rpc_error_is_bounded_and_drops_error_data(self):
        from agentnik.mcp_support import rpc_error
        message={'jsonrpc':'2.0','id':2,'error':{'code':-32602,'message':'bad\nquery '+('x'*700),'data':{'secret':'never-show'}}}
        result=rpc_error(message);self.assertIn('-32602',result);self.assertIn('bad query',result);self.assertNotIn('never-show',result);self.assertNotIn('\n',result);self.assertLess(len(result),600)
        for error in ({'code':True,'message':'bad'},{'code':-1,'message':3},'bad'):
            with self.subTest(error=error),self.assertRaises(ValueError):rpc_error({'error':error})
        with self.assertRaises(ValueError):rpc_error({'error':{'code':-1,'message':'bad'},'result':{}})

    def test_local_call_rpc_error_reports_diagnostic_and_uncertainty(self):
        os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
        from PySide6.QtCore import QEventLoop,QTimer
        from PySide6.QtWidgets import QApplication
        from agentnik.mcp_local import LocalSession
        app=QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as folder:
            server=Path(folder)/'error.py';marker=Path(folder)/'calls'
            server.write_text('''import json,sys,pathlib
for line in sys.stdin:
 req=json.loads(line);method=req['method']
 if method=='notifications/initialized':continue
 if method=='initialize':result={'protocolVersion':req['params']['protocolVersion'],'serverInfo':{'name':'Fake','version':'1'},'capabilities':{'tools':{}}}
 elif method=='tools/list':result={'tools':[{'name':'query','inputSchema':{'type':'object'}}]}
 else:
  pathlib.Path(sys.argv[1]).write_text('once');print(json.dumps({'jsonrpc':'2.0','id':req['id'],'error':{'code':-32602,'message':'Invalid query parameter','data':'private data'}}),flush=True);continue
 print(json.dumps({'jsonrpc':'2.0','id':req['id'],'result':result}),flush=True)
''',encoding='utf-8')
            session=LocalSession(sys.executable,[str(server),str(marker)],prefer_modern=False);loop=QEventLoop();out=[]
            session.discovered.connect(lambda info:session.call(info['tool_details'][0],{}));session.ended.connect(lambda result:(out.append(result),loop.quit()))
            session.start();QTimer.singleShot(5000,loop.quit);loop.exec();session.close()
            self.assertIn('-32602',out[0]['error']);self.assertIn('Invalid query parameter',out[0]['error']);self.assertNotIn('private data',str(out));self.assertTrue(out[0]['call_uncertain']);self.assertTrue(marker.exists())

    def test_local_timed_out_call_is_uncertain_and_not_replayed(self):
        os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
        from PySide6.QtCore import QEventLoop,QTimer
        from PySide6.QtWidgets import QApplication
        from agentnik.mcp_local import LocalSession
        app=QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as folder:
            server=Path(folder)/'slow.py';marker=Path(folder)/'calls'
            server.write_text('''import json,sys,pathlib,time
for line in sys.stdin:
 req=json.loads(line);method=req['method']
 if method=='notifications/initialized':continue
 if method=='initialize':result={'protocolVersion':req['params']['protocolVersion'],'serverInfo':{'name':'Fake','version':'1'},'capabilities':{'tools':{}}}
 elif method=='tools/list':result={'tools':[{'name':'query','inputSchema':{'type':'object'}}]}
 else:
  pathlib.Path(sys.argv[1]).write_text('once');time.sleep(5);continue
 print(json.dumps({'jsonrpc':'2.0','id':req['id'],'result':result}),flush=True)
''',encoding='utf-8')
            session=LocalSession(sys.executable,[str(server),str(marker)],timeout_seconds=1,prefer_modern=False);loop=QEventLoop();out=[]
            session.discovered.connect(lambda info:session.call(info['tool_details'][0],{}));session.ended.connect(lambda result:(out.append(result),loop.quit()))
            session.start();QTimer.singleShot(5000,loop.quit);loop.exec();session.close()
            self.assertEqual(marker.read_text(),'once');self.assertTrue(out[0]['call_uncertain']);self.assertIn('timed out',out[0]['error'])

    def test_remote_call_rpc_error_reports_diagnostic_and_uncertainty(self):
        import threading
        from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
        os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
        from PySide6.QtCore import QEventLoop,QTimer
        from PySide6.QtWidgets import QApplication
        from agentnik.mcp_remote import RemoteSession
        calls=[]
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def do_POST(self):
                request=json.loads(self.rfile.read(int(self.headers['Content-Length'])));method=request['method'];calls.append(method)
                if method=='notifications/initialized':self.send_response(202);self.end_headers();return
                if method=='initialize':result={'protocolVersion':PROTOCOL,'serverInfo':{'name':'Fake','version':'1'},'capabilities':{'tools':{}}}
                elif method=='tools/list':result={'tools':[{'name':'query','inputSchema':{'type':'object'}}]}
                else:result=None
                msg={'jsonrpc':'2.0','id':request['id']}
                if result is None:msg['error']={'code':-32603,'message':'Database unavailable','data':'private data'}
                else:msg['result']=result
                payload=json.dumps(msg).encode();self.send_response(200);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(payload)));self.send_header('Mcp-Session-Id','session');self.end_headers();self.wfile.write(payload)
            def do_DELETE(self):self.send_response(204);self.end_headers()
        app=QApplication.instance() or QApplication([]);server=ThreadingHTTPServer(('127.0.0.1',0),Handler);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        try:
            session=RemoteSession('http://127.0.0.1:'+str(server.server_port)+'/mcp','',prefer_modern=False);loop=QEventLoop();out=[]
            session.discovered.connect(lambda info:session.call(info['tool_details'][0],{}));session.ended.connect(lambda result:(out.append(result),loop.quit()))
            session.start();QTimer.singleShot(5000,loop.quit);loop.exec();session.shutdown()
            self.assertIn('-32603',out[0]['error']);self.assertIn('Database unavailable',out[0]['error']);self.assertNotIn('private data',str(out));self.assertTrue(out[0]['call_uncertain']);self.assertEqual(calls.count('tools/call'),1)
        finally:server.shutdown();server.server_close();thread.join(2)

    def test_remote_validation_and_sse_messages(self):
        from agentnik.mcp_remote import response_message,preview_tool
        remote={'name':'Parallel','transport':'http','url':'https://mcp.parallel.ai/mcp','credential_id':'opaque','enabled':True}
        validate_servers([remote])
        for url in ('http://example.com/mcp','https://user:secret@example.com/mcp','https://example.com/mcp?key=secret'):
            with self.assertRaises(ValueError):validate_servers([dict(remote,url=url)])
        body=b': keepalive\n\ndata: {"jsonrpc":"2.0","id":1,"result":{}}\n\n'
        self.assertEqual(response_message(body,'text/event-stream',1)['id'],1)
        for newline in (b'\n',b'\r\n',b'\r'):
            framed=newline.join([b'\xef\xbb\xbf: comment',b'id: 1',b'data:',b'',b'event: message',b'data: {"jsonrpc":"2.0",',b'data: "id":1,"result":{}}',b'',b''])
            self.assertEqual(response_message(framed,'text/event-stream',1)['id'],1)
        for incomplete in (b'data: {"jsonrpc":"2.0","id":1}\n',body+b'data: {"jsonrpc":',body+b'data:'):
            with self.subTest(incomplete=incomplete),self.assertRaises(ValueError):response_message(incomplete,'text/event-stream',1)
        with self.assertRaises(ValueError):response_message(body+body,'text/event-stream',1)
        with self.assertRaises(ValueError):response_message(b'{"jsonrpc":"2.0","id":9}','application/json',1)
        detail=preview_tool({'description':'Search','inputSchema':{'type':'object'}})
        self.assertEqual(detail['schema'],{'type':'object'});self.assertEqual(detail['schema_status'],'available')
        self.assertEqual(preview_tool({'description':'x'*9000,'inputSchema':{'long':'a'*33000}})['schema_status'],'oversized')
        self.assertTrue(preview_tool({'description':'x'*9000})['description_clipped'])
        self.assertEqual(preview_tool({})['schema_status'],'missing')
        self.assertEqual(preview_tool({'execution':{'taskSupport':'required'}})['task_support'],'required')
        hints={'title':'Search','readOnlyHint':True,'destructiveHint':False,'openWorldHint':True}
        self.assertEqual(preview_tool({'annotations':hints})['annotations'],hints)
        for invalid in (None,{'readOnlyHint':1},{'title':'bad\nname'}):
            with self.assertRaises(ValueError):preview_tool({'annotations':invalid})
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
                if method=='tools/call' and body['params']['arguments'].get('query')=='uncertain':
                    incomplete=('data: '+json.dumps({'jsonrpc':'2.0','id':body['id'],'result':{'content':[]}})+'\r').encode()
                    self.send_response(200);self.send_header('Content-Type','text/event-stream');self.send_header('Content-Length',str(len(incomplete)));self.end_headers();self.wfile.write(incomplete);return
                if method=='initialize':result={'protocolVersion':PROTOCOL,'serverInfo':{'name':'Fake','version':''},'capabilities':{'tools':{}}}
                elif method=='tools/call':result={'content':[{'type':'text','text':'A search result'}],'isError':False}
                elif not body.get('params',{}).get('cursor'):result={'tools':[{'name':'web_search','description':'Search the web','inputSchema':{'type':'object','properties':{'query':{'type':'string'}}},'outputSchema':{'type':'object','properties':{'items':{'type':'array','items':{'type':'string'}}}}}],'nextCursor':'page-2'}
                else:result={'tools':[{'name':'web_fetch','inputSchema':{'type':'object'}}]}
                payload=('data: '+json.dumps({'jsonrpc':'2.0','id':body['id'],'result':result})+'\r\r').encode()
                self.send_response(200);self.send_header('Content-Type','text/event-stream');self.send_header('Content-Length',str(len(payload)));self.send_header('Mcp-Session-Id','session-1');self.end_headers();self.wfile.write(payload)
            def do_DELETE(self):
                calls.append(('DELETE',self.headers.get('Mcp-Session-Id'),self.headers.get('MCP-Protocol-Version'),self.headers.get('Authorization')));self.send_response(204);self.end_headers()
        app=QApplication.instance() or QApplication([]);server=ThreadingHTTPServer(('127.0.0.1',0),Handler);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        try:
            loop=QEventLoop();probe=RemoteProbe('http://127.0.0.1:'+str(server.server_port)+'/mcp','test-token',prefer_modern=False);results=[]
            probe.finished.connect(lambda result:(results.append(result),loop.quit()));probe.start();QTimer.singleShot(5000,loop.quit);loop.exec()
            self.assertEqual(results[0]['tools'],['web_search','web_fetch']);self.assertEqual(results[0]['version'],'unknown');self.assertTrue(results[0]['session_closed'])
            self.assertEqual(results[0]['tool_details'][0]['description'],'Search the web');self.assertIn('query',results[0]['tool_details'][0]['schema']['properties'])
            self.assertEqual([call[0] for call in calls],['initialize','notifications/initialized','tools/list','tools/list','DELETE'])
            self.assertTrue(all(call[1:3]==('session-1',PROTOCOL) for call in calls[1:]));self.assertTrue(all(call[3]=='Bearer test-token' for call in calls))
            loop2=QEventLoop();probe2=RemoteProbe('http://127.0.0.1:'+str(server.server_port)+'/mcp','test-token',invocation={'tool':results[0]['tool_details'][0],'arguments':{'query':'MCP'}},prefer_modern=False);calls_result=[]
            probe2.finished.connect(lambda result:(calls_result.append(result),loop2.quit()));probe2.start();QTimer.singleShot(5000,loop2.quit);loop2.exec()
            self.assertEqual(calls_result[0]['call_result']['content'][0]['text'],'A search result');self.assertEqual([call[0] for call in calls].count('tools/call'),1)
            altered=dict(results[0]['tool_details'][0],description='stale');loop3=QEventLoop();probe3=RemoteProbe('http://127.0.0.1:'+str(server.server_port)+'/mcp','test-token',invocation={'tool':altered,'arguments':{'query':'MCP'}},prefer_modern=False);stale=[]
            probe3.finished.connect(lambda result:(stale.append(result),loop3.quit()));probe3.start();QTimer.singleShot(5000,loop3.quit);loop3.exec()
            self.assertIn('error',stale[0]);self.assertTrue(stale[0]['session_closed']);self.assertEqual(calls[-1][0],'DELETE');self.assertEqual([call[0] for call in calls].count('tools/call'),1)
            changed_output=dict(results[0]['tool_details'][0],output_schema={'type':'object','required':['changed']});loop5=QEventLoop();probe5=RemoteProbe('http://127.0.0.1:'+str(server.server_port)+'/mcp','test-token',invocation={'tool':changed_output,'arguments':{'query':'MCP'}},prefer_modern=False);out5=[]
            probe5.finished.connect(lambda result:(out5.append(result),loop5.quit()));probe5.start();QTimer.singleShot(5000,loop5.quit);loop5.exec()
            self.assertIn('definition changed',out5[0]['error']);self.assertFalse(out5[0]['call_uncertain']);self.assertEqual([call[0] for call in calls].count('tools/call'),1)
            loop4=QEventLoop();probe4=RemoteProbe('http://127.0.0.1:'+str(server.server_port)+'/mcp','test-token',invocation={'tool':results[0]['tool_details'][0],'arguments':{'query':'uncertain'}},prefer_modern=False);uncertain=[]
            probe4.finished.connect(lambda result:(uncertain.append(result),loop4.quit()));probe4.start();QTimer.singleShot(5000,loop4.quit);loop4.exec()
            self.assertTrue(uncertain[0]['call_uncertain']);self.assertTrue(uncertain[0]['session_closed']);self.assertEqual(calls[-1][0],'DELETE');self.assertEqual([call[0] for call in calls].count('tools/call'),2)
        finally:server.shutdown();server.server_close();thread.join(2)

    def test_manual_remote_failure_preserves_error_when_cleanup_fails(self):
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
                if body['method']=='initialize':
                    result={'protocolVersion':PROTOCOL,'serverInfo':{'name':'Fake','version':'1'},'capabilities':{'tools':{}}}
                    payload=json.dumps({'jsonrpc':'2.0','id':body['id'],'result':result}).encode()
                    self.send_response(200);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(payload)));self.send_header('Mcp-Session-Id','session');self.end_headers();self.wfile.write(payload);return
                self.send_response(503);self.end_headers()
            def do_DELETE(self):
                calls.append(('DELETE',self.headers.get('Authorization'),self.headers.get('Mcp-Session-Id')));self.send_response(405);self.end_headers()
        app=QApplication.instance() or QApplication([]);server=ThreadingHTTPServer(('127.0.0.1',0),Handler);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        try:
            probe=RemoteProbe('http://127.0.0.1:'+str(server.server_port)+'/mcp','fixture-secret',prefer_modern=False);out=[];loop=QEventLoop()
            probe.finished.connect(lambda result:(out.append(result),loop.quit()));probe.start();QTimer.singleShot(5000,loop.quit);loop.exec()
            self.assertEqual(len(out),1);self.assertIn('503',out[0]['error']);self.assertFalse(out[0]['call_uncertain']);self.assertFalse(out[0]['session_closed'])
            self.assertEqual(calls[-1],('DELETE','Bearer fixture-secret','session'));self.assertNotIn('fixture-secret',str(out));self.assertEqual(probe.token,'')
        finally:server.shutdown();server.server_close();thread.join(2)

    def test_remote_cleanup_after_identity_mismatch_and_oversized_response(self):
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
                if body['method']=='initialize':result={'protocolVersion':PROTOCOL,'serverInfo':{'name':'Fake','version':'1'},'capabilities':{'tools':{}}}
                else:result={'tools':[],'padding':'x'*140000}
                payload=json.dumps({'jsonrpc':'2.0','id':body['id'],'result':result}).encode()
                self.send_response(200);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(payload)));self.send_header('Mcp-Session-Id','session');self.end_headers();self.wfile.write(payload)
            def do_DELETE(self):calls.append('DELETE');self.send_response(204);self.end_headers()
        app=QApplication.instance() or QApplication([]);server=ThreadingHTTPServer(('127.0.0.1',0),Handler);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        try:
            for expected in ({'name':'Different'},None):
                with self.subTest(expected=expected):
                    calls.clear();out=[];loop=QEventLoop()
                    probe=RemoteProbe('http://127.0.0.1:'+str(server.server_port)+'/mcp','',expected_identity=expected,prefer_modern=False)
                    probe.finished.connect(lambda result:(out.append(result),loop.quit()));probe.start();QTimer.singleShot(5000,loop.quit);loop.exec()
                    self.assertEqual(len(out),1);self.assertIn('error',out[0]);self.assertTrue(out[0]['session_closed']);self.assertEqual(calls[-1],'DELETE')
                    self.assertFalse(out[0]['call_uncertain'])
        finally:server.shutdown();server.server_close();thread.join(2)

    def test_manual_remote_timeout_attempts_cleanup_without_replaying_call(self):
        import threading
        from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
        os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
        from PySide6.QtCore import QEventLoop,QTimer
        from PySide6.QtWidgets import QApplication
        from agentnik.mcp_remote import RemoteProbe,preview_tool
        calls=[];release=threading.Event()
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def do_POST(self):
                body=json.loads(self.rfile.read(int(self.headers['Content-Length'])));method=body['method'];calls.append(method)
                if method=='notifications/initialized':self.send_response(202);self.end_headers();return
                if method=='notifications/cancelled':self.send_response(202);self.end_headers();return
                if method=='tools/call':release.wait(5);return
                if method=='initialize':result={'protocolVersion':PROTOCOL,'serverInfo':{'name':'Fake','version':'1'},'capabilities':{'tools':{}}}
                else:result={'tools':[{'name':'query','inputSchema':{'type':'object'}}]}
                payload=json.dumps({'jsonrpc':'2.0','id':body['id'],'result':result}).encode()
                self.send_response(200);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(payload)));self.send_header('Mcp-Session-Id','session');self.end_headers();self.wfile.write(payload)
            def do_DELETE(self):calls.append('DELETE');self.send_response(204);self.end_headers()
        app=QApplication.instance() or QApplication([]);server=ThreadingHTTPServer(('127.0.0.1',0),Handler);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        try:
            tool=dict(preview_tool({'inputSchema':{'type':'object'}}),name='query');out=[];loop=QEventLoop()
            probe=RemoteProbe('http://127.0.0.1:'+str(server.server_port)+'/mcp','',invocation={'tool':tool,'arguments':{}},timeout_seconds=1,prefer_modern=False)
            probe.finished.connect(lambda result:(out.append(result),loop.quit()));probe.start();QTimer.singleShot(5000,loop.quit);loop.exec()
            self.assertEqual(len(out),1);self.assertIn('timed out',out[0]['error']);self.assertTrue(out[0]['call_uncertain']);self.assertTrue(out[0]['session_closed'])
            self.assertEqual(calls.count('tools/call'),1);self.assertEqual(calls[-1],'DELETE')
        finally:release.set();server.shutdown();server.server_close();thread.join(2)

    def test_remote_protocol_negotiation_and_headers(self):
        import threading
        from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
        os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
        from PySide6.QtCore import QEventLoop,QTimer
        from PySide6.QtWidgets import QApplication
        from agentnik.mcp_remote import RemoteProbe,RemoteSession
        calls=[];selected=['2025-06-18']
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def do_POST(self):
                body=json.loads(self.rfile.read(int(self.headers['Content-Length'])));method=body['method'];header=self.headers.get('MCP-Protocol-Version');calls.append((method,header))
                if method!='initialize' and header!=selected[0]:self.send_response(400);self.end_headers();return
                if method=='notifications/initialized':self.send_response(202);self.end_headers();return
                if method=='initialize':result={'protocolVersion':selected[0],'serverInfo':{'name':'Older','version':'1'},'capabilities':{'tools':{}}}
                elif method=='tools/list':result={'tools':[{'name':'echo','inputSchema':{'type':'object'}}]}
                else:result={'content':[{'type':'text','text':'ok'}]}
                payload=json.dumps({'jsonrpc':'2.0','id':body['id'],'result':result}).encode();self.send_response(200);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(payload)));self.send_header('Mcp-Session-Id','session');self.end_headers();self.wfile.write(payload)
            def do_DELETE(self):
                header=self.headers.get('MCP-Protocol-Version');calls.append(('DELETE',header));self.send_response(204 if header==selected[0] else 400);self.end_headers()
        app=QApplication.instance() or QApplication([]);server=ThreadingHTTPServer(('127.0.0.1',0),Handler);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        try:
            url='http://127.0.0.1:'+str(server.server_port)+'/mcp'
            for version in ('2025-06-18','2025-03-26'):
                with self.subTest(version=version):
                    selected[0]=version;calls.clear();loop=QEventLoop();session=RemoteSession(url,'',prefer_modern=False);results=[]
                    def discovered(info):
                        results.append(info);self.assertTrue(session.call(info['tool_details'][0],{}))
                    session.discovered.connect(discovered);session.called.connect(lambda result:(results.append(result),session.shutdown()));session.finished.connect(lambda result:(results.append(result),loop.quit()));session.start();QTimer.singleShot(5000,loop.quit);loop.exec()
                    self.assertEqual(results[0]['protocol'],version);self.assertEqual(results[1]['call_result']['content'][0]['text'],'ok');self.assertTrue(results[2]['session_closed'])
                    self.assertEqual([item[0] for item in calls],['initialize','notifications/initialized','tools/list','tools/list','tools/call','DELETE'])
                    self.assertIsNone(calls[0][1]);self.assertTrue(all(header==version for _,header in calls[1:]))
            selected[0]='2024-11-05';calls.clear();loop=QEventLoop();probe=RemoteProbe(url,'',prefer_modern=False);results=[]
            probe.finished.connect(lambda result:(results.append(result),loop.quit()));probe.start();QTimer.singleShot(5000,loop.quit);loop.exec()
            self.assertIn('error',results[0]);self.assertEqual(calls,[('initialize',None)])
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
            loop=QEventLoop();probe=RemoteProbe('http://127.0.0.1:'+str(server.server_port)+'/mcp','',prefer_modern=False);results=[]
            probe.finished.connect(lambda result:(results.append(result),loop.quit()));probe.start();QTimer.singleShot(5000,loop.quit);loop.exec()
            self.assertIn('error',results[0]);self.assertEqual(calls.count('tools/list'),2)
        finally:server.shutdown();server.server_close();thread.join(2)

    def test_manager_explains_unsaved_server_and_invalid_windows_json(self):
        os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
        from PySide6.QtWidgets import QApplication,QMessageBox
        from agentnik.mcp_ui import MCPServers
        from agentnik.ui import Window
        app=QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as folder,patch('agentnik.core.discover',return_value={}),patch('agentnik.core.environment_connections',return_value={}):
            store=Store(folder);window=Window(store);dialog=MCPServers(window)
            try:
                dialog.name.setText('Local');dialog.command.setText(sys.executable)
                dialog.args.setPlainText('["D:\\dev\\parquet_mcp\\server.py"]')
                dialog.test();self.assertIn('Save and select',dialog.status.text())
                with patch.object(QMessageBox,'warning') as warning:
                    dialog.save();self.assertIn('double each backslash',warning.call_args.args[2])
                self.assertEqual(store.config.get('mcp_servers',[]),[])
                dialog.args.setPlainText('["D:/dev/parquet_mcp/server.py"]');dialog.save()
                self.assertEqual(store.config['mcp_servers'][0]['args'],['D:/dev/parquet_mcp/server.py'])
                dialog.args.setPlainText('["D:/dev/parquet_mcp/different.py"]')
                with patch.object(QMessageBox,'question') as confirm:
                    dialog.test();confirm.assert_not_called()
                self.assertIn('Save your changes',dialog.status.text());self.assertIsNone(dialog.process)
            finally:dialog.close();window.close();app.processEvents();store.db.close()

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
 if method=='server/discover':print(json.dumps({'jsonrpc':'2.0','id':request['id'],'error':{'code':-32601,'message':'unsupported'}}),flush=True);continue
 if method=='notifications/initialized': continue
 if method=='initialize': result={'protocolVersion':request['params']['protocolVersion'],'serverInfo':{'name':'Fake','version':'1'},'capabilities':{'tools':{}}}
 elif method=='tools/list': result={'tools':[{'name':'query','description':'Run a query','inputSchema':{'type':'object'},'annotations':{'readOnlyHint':True}}]}
 else: result={'content':[{'type':'text','text':'success'}]}
 print(json.dumps({'jsonrpc':'2.0','id':request['id'],'result':result}),flush=True)
''',encoding='utf-8')
            store=Store(root/'data');store.config['mcp_servers']=[{'name':'Fake','command':sys.executable,'args':[str(server),str(marker)],'enabled':True,'working_directory':str(root)}];store.flush();window=Window(store)
            try:
                dialog=MCPServers(window);dialog.list.setCurrentRow(0);self.assertFalse(marker.exists())
                with patch.object(QMessageBox,'question',return_value=QMessageBox.StandardButton.Yes) as review:
                    dialog.test();review.assert_not_called()
                loop=QEventLoop();timer=QTimer();timer.timeout.connect(lambda:loop.quit() if dialog.discovered else None);timer.start(10);QTimer.singleShot(5000,loop.quit);loop.exec();timer.stop()
                self.assertIsNotNone(dialog.process);self.assertTrue(marker.exists());self.assertIn('Connected: Fake',dialog.status.text());self.assertEqual(dialog.tool_choice.currentText(),'query')
                session=dialog.process;results=[];session.called.connect(lambda result:results.append(result))
                for _ in range(2):
                    self.assertTrue(session.call(dialog.discovered['tools'][0],{}));loop=QEventLoop();timer=QTimer();timer.timeout.connect(lambda:loop.quit() if len(results)>_ else None);timer.start(10);QTimer.singleShot(5000,loop.quit);loop.exec();timer.stop()
                self.assertEqual(len(results),2);self.assertEqual(results[1]['call_result']['content'][0]['text'],'success')
                with patch.object(QDialog,'exec',return_value=QDialog.DialogCode.Accepted) as review_call:
                    dialog.call_remote();loop=QEventLoop();timer=QTimer();timer.timeout.connect(lambda:loop.quit() if len(results)>2 else None);timer.start(10);QTimer.singleShot(5000,loop.quit);loop.exec();timer.stop()
                    review_call.assert_not_called()
                self.assertEqual(len(results),3);self.assertIn('success',dialog.tool_result.toPlainText());dialog.finish_test('Closed');dialog.close()
            finally:window.close();app.processEvents();store.db.close()

    def test_resource_template_expansion_and_pagination(self):
        from agentnik.mcp_resources import TemplatePages,expand_template
        self.assertEqual(expand_template('test://item/{id}',{'id':'a/b ?'}),'test://item/a%2Fb%20%3F')
        self.assertEqual(expand_template('test://x{/id,part}{?query,empty}{&next}',{'id':'a/b','part':'雪','query':'a&b =','empty':'','next':'%'}),'test://x/a%2Fb/%E9%9B%AA?query=a%26b%20%3D&empty=&next=%25')
        self.assertEqual(expand_template('test://x/{a,b}/{a}',{'a':'x,y','b':'z'}),'test://x/x%2Cy,z/x%2Cy')
        self.assertEqual(expand_template('test://x{/a,b}{?q,limit}{&next}',{'b':'','limit':'10','next':None}),'test://x/?limit=10')
        self.assertEqual(expand_template('test://x{/id}{?q}',{}),'test://x')
        self.assertEqual(expand_template('test://x/{a,b}',{'b':'test'}),'test://x/test')
        self.assertEqual(expand_template('test://x{?q}',{'q':''}),'test://x?q=')
        self.assertEqual(expand_template('test://x/{+path}',{'path':'a/b%20c?x=1&y=雪%bad%'}),'test://x/a/b%20c?x=1&y=%E9%9B%AA%bad%25')
        self.assertEqual(expand_template('test://x{#x,y}',{'x':'a/b','y':'q r'}),'test://x#a/b,q%20r')
        self.assertEqual(expand_template('test://x{.x,y}{;x,y,empty}',{'x':'a/b','y':'hello','empty':''}),'test://x.a%2Fb.hello;x=a%2Fb;y=hello;empty')
        self.assertEqual(expand_template('test://x{#x}{.x}{;x}',{}),'test://x')
        self.assertEqual(expand_template('test://x/{name:3}{?name:2}',{'name':'雪山/p'}),'test://x/%E9%9B%AA%E5%B1%B1%2F?name=%E9%9B%AA%E5%B1%B1')
        self.assertEqual(expand_template('test://x/{+path:4}',{'path':'abc/def'}),'test://x/abc/')
        self.assertEqual(expand_template('test://x/{+path:2}',{'path':'a%2Fb'}),'test://x/a%2F')
        self.assertEqual(expand_template('test://x/{+path:1}',{'path':'%E9%9B%AAx'}),'test://x/%E9%9B%AA')
        self.assertEqual(expand_template('test://x/{path:1}',{'path':'%E9%9B%AAx'}),'test://x/%25E9%259B%25AA')
        self.assertEqual(expand_template('test://x/{+path:1}',{'path':'%E9%FFabc'}),'test://x/%E9')
        for template,values in [('{id}',{}),('test://x/{id}',{'id':[1]}),('test://x/{id',{'id':'a'}),('test://x/{x:2*}',{'x':'a'}),('test://x/{x:0}',{'x':'a'}),('test://x/{x:10000}',{'x':'a'}),('test://x/{?x}',{'x':'a','extra':'b'}),('test://x/{/x}',{'x':'a'*2040}),('test://x/{x:2}',{'x':['a']}),('test://x/{x}',{'x':['a']*65})]:
            with self.subTest(template=template),self.assertRaises(ValueError):expand_template(template,values)
        pages=TemplatePages();cursor,result=pages.accept({'resourceTemplates':[{'uriTemplate':'test://x/{id}','name':'One'},{'uriTemplate':'test://x/{+id}','name':'Complex'}],'nextCursor':'next'})
        self.assertEqual(cursor,'next');self.assertTrue(result['templates'][0]['supported']);self.assertTrue(result['templates'][1]['supported'])
        query=TemplatePages().accept({'resourceTemplates':[{'uriTemplate':'test://x{/id}{?q,limit}','name':'Search'}]})[1]['templates'][0]
        self.assertTrue(query['supported']);self.assertEqual(query['variables'],['id','q','limit'])
        with self.assertRaises(ValueError):pages.accept({'resourceTemplates':[],'nextCursor':'next'})

    def test_resource_template_composite_expansion(self):
        from agentnik.mcp_resources import expand_template,template_variables
        values={'list':['red','green','blue'],'keys':{'semi':';','dot':'.','comma':','}}
        cases={'{list}':'red,green,blue','{list*}':'red,green,blue','{keys}':'semi,%3B,dot,.,comma,%2C','{keys*}':'semi=%3B,dot=.,comma=%2C','{+keys*}':'semi=;,dot=.,comma=,','{#list*}':'#red,green,blue','{.list*}':'.red.green.blue','{/list*}':'/red/green/blue','{;list}':';list=red,green,blue','{;list*}':';list=red;list=green;list=blue','{?list*}':'?list=red&list=green&list=blue','{?keys*}':'?semi=%3B&dot=.&comma=%2C','{&keys*}':'&semi=%3B&dot=.&comma=%2C'}
        for expression,expected in cases.items():
            selected={name:value for name,value in values.items() if name in template_variables(expression)}
            with self.subTest(expression=expression):self.assertEqual(expand_template('test://x'+expression,selected),'test://x'+expected)
        self.assertEqual(expand_template('test://x{?a*,b*}',{'a':[],'b':{}}),'test://x')
        self.assertEqual(expand_template('test://x{;a*,b*}',{'a':[''],'b':{'key':''}}),'test://x;a;key')
        self.assertEqual(expand_template('test://x{?1.name,%62}',{'1.name':'yes','%62':'ok'}),'test://x?1.name=yes&%62=ok')

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
 elif method=='resources/templates/list':result={'resourceTemplates':[{'uriTemplate':'test://item/{+id:2}{?q*}','name':'Item'}]}
 elif method=='resources/read':result={'contents':[{'uri':req['params']['uri'],'text':'content'}]}
 else:raise RuntimeError('unexpected')
 print(json.dumps({'jsonrpc':'2.0','id':req['id'],'result':result}),flush=True)
''',encoding='utf-8')
            session=LocalSession(sys.executable,[str(server)],prefer_modern=False);loop=QEventLoop();out=[]
            def received(result):
                out.append(result)
                if len(out)==1:
                    template=result['templates'][0];values={'id':'a%2Fb','q':['x&y','z']};self.assertFalse(session.read_resource_template(template,values,'test://item/a%2?q=x%26y&q=z'));self.assertTrue(session.read_resource_template(template,values,'test://item/a%2F?q=x%26y&q=z'))
                else:loop.quit()
            session.discovered.connect(lambda _:session.list_resource_templates());session.resources.connect(received);session.ended.connect(lambda result:(out.append(result),loop.quit()));session.start();QTimer.singleShot(5000,loop.quit);loop.exec();session.close()
            self.assertEqual(out[1]['contents'][0]['uri'],'test://item/a%2F?q=x%26y&q=z');self.assertEqual(out[1]['contents'][0]['text'],'content')

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

    def test_prompt_embedded_resources_and_audience(self):
        from agentnik.mcp_prompts import parse_prompt_messages
        messages=[{'role':'user','content':{'type':'resource','resource':{'uri':'file:///guide.md','mimeType':'text/markdown','text':'Public guide'}}},
                  {'role':'assistant','content':{'type':'text','text':'Private text','annotations':{'audience':['user']}}},
                  {'role':'user','content':{'type':'resource','resource':{'uri':'file:///private','text':'Private guide'},'annotations':{'audience':['user']}}}]
        result=parse_prompt_messages({'messages':messages})
        self.assertEqual(result['messages'][0]['content']['resource']['text'],'Public guide')
        self.assertEqual(result['user_text'],['Private text','Private guide']);self.assertNotIn('Private',json.dumps(result['messages']))
        import base64
        encoded=base64.b64encode('제목'.encode()).decode()
        result=parse_prompt_messages({'messages':[{'role':'user','content':{'type':'resource','resource':{'uri':'file:///guide','mimeType':'text/plain','blob':encoded}}}]})
        self.assertEqual(result['messages'][0]['content']['resource']['text'],'제목')
        for content in ({'type':'resource','resource':{'uri':'file:///x','blob':'AAAA'}},
                        {'type':'resource','resource':{'uri':'file:///x','text':'x'*32001}},
                        {'type':'resource','resource':{'uri':'bad\nuri','text':'x'}},
                        {'type':'text','text':'secret','annotations':{'audience':'user'}}):
            with self.subTest(content=content),self.assertRaises(ValueError):parse_prompt_messages({'messages':[{'role':'user','content':content}]})

    def test_mcp_prompt_image_response_limit(self):
        from agentnik.mcp_support import response_limit,MAX_TOOL_RESULT_OUTPUT,MAX_OUTPUT
        self.assertEqual(response_limit('prompt_get'),MAX_TOOL_RESULT_OUTPUT)
        self.assertEqual(response_limit('prompt_list'),MAX_OUTPUT)

    def test_local_prompt_with_large_image_content(self):
        import base64
        from test_image_generation import png
        from agentnik.mcp_content import model_images
        os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
        from PySide6.QtCore import QEventLoop,QTimer
        from PySide6.QtWidgets import QApplication
        from agentnik.mcp_local import LocalSession
        app=QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as folder:
            server=Path(folder)/'image_prompt.py'
            data=png()+b'x'*(1024*1024);(Path(folder)/'image.png').write_bytes(data)
            server.write_text('''import base64,json,sys,pathlib
for line in sys.stdin:
 req=json.loads(line);method=req['method']
 if method=='notifications/initialized':continue
 if method=='initialize':result={'protocolVersion':req['params']['protocolVersion'],'serverInfo':{'name':'Fake','version':'1'},'capabilities':{'prompts':{}}}
 elif method=='prompts/list':result={'prompts':[{'name':'image'}]}
 elif method=='prompts/get':result={'messages':[{'role':'user','content':{'type':'image','mimeType':'image/png','data':base64.b64encode(pathlib.Path(__file__).with_name('image.png').read_bytes()).decode()}}]}
 else:raise RuntimeError('unexpected')
 print(json.dumps({'jsonrpc':'2.0','id':req['id'],'result':result}),flush=True)
''',encoding='utf-8')
            session=LocalSession(sys.executable,[str(server)],prefer_modern=False);loop=QEventLoop();out=[]
            def response(result):
                out.append(result)
                if len(out)==1:self.assertTrue(session.list_prompts({'prompt':result['prompts'][0],'arguments':{}}))
                else:loop.quit()
            session.discovered.connect(lambda _:session.list_prompts());session.prompts.connect(response);session.ended.connect(lambda result:(out.append(result),loop.quit()));session.start();QTimer.singleShot(5000,loop.quit);loop.exec();session.close()
            content=out[1]['messages'][0]['content'];self.assertEqual(content['data'],base64.b64encode(data).decode('ascii'))
            transformed,images=model_images({'content':[content]},True,1,'test')
            self.assertEqual(images[0][1],data);self.assertNotIn(content['data'],json.dumps(transformed))

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
            session=LocalSession(sys.executable,[str(server),str(marker)],prefer_modern=False);loop=QEventLoop();out=[]
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
 elif method=='resources/read':result={'contents':[{'uri':req['params']['uri'],'blob':'UmVzb3VyY2UgdGV4dA==','mimeType':'text/plain'}]}
 else:raise RuntimeError('unexpected')
 print(json.dumps({'jsonrpc':'2.0','id':req['id'],'result':result}),flush=True)
''',encoding='utf-8')
            session=LocalSession(sys.executable,[str(server)],prefer_modern=False);loop=QEventLoop();results=[]
            def ready(info):
                self.assertIn('resources',info['capabilities']);self.assertTrue(session.list_resources())
            def resource(result):
                results.append(result)
                if len(results)==1:
                    self.assertFalse(session.read_resource('test://unlisted'));self.assertTrue(session.read_resource(result['resources'][1]['uri']))
                else:loop.quit()
            session.discovered.connect(ready);session.resources.connect(resource);session.ended.connect(lambda result:(results.append(result),loop.quit()));session.start();QTimer.singleShot(5000,loop.quit);loop.exec();session.close()
            self.assertEqual(results[0]['resources'][0]['name'],'Record');self.assertFalse(results[0]['more_resources']);self.assertEqual(results[0]['resources'][1]['name'],'Second');self.assertEqual(results[1]['contents'][0]['text'],'Resource text')

    def test_resource_images_validate_mime_base64_and_requested_uri(self):
        import base64
        from test_image_generation import png
        from agentnik.mcp_resources import parse_resource_contents
        from agentnik.mcp_support import response_limit,MAX_RESOURCE_RESULT_OUTPUT
        encoded=base64.b64encode(png()).decode()
        item={'uri':'test://chart','mimeType':'image/png','blob':encoded}
        self.assertEqual(parse_resource_contents({'contents':[item]},'test://chart')['contents'][0],item)
        self.assertEqual(response_limit('resource_read'),MAX_RESOURCE_RESULT_OUTPUT)
        for invalid in (dict(item,mimeType='image/jpeg'),dict(item,blob='bad base64'),dict(item,uri='test://other'),dict(item,mimeType='application/pdf'),dict(item,text='also text')):
            with self.subTest(invalid=invalid),self.assertRaises(ValueError):parse_resource_contents({'contents':[invalid]},'test://chart')

    def test_resource_and_prompt_allow_images_beyond_previous_limits(self):
        import base64
        from test_image_generation import png
        from agentnik.mcp_resources import parse_resource_contents
        from agentnik.mcp_prompts import parse_prompt_messages
        data=png()+b'x'*(12*1024*1024+100);encoded=base64.b64encode(data).decode('ascii')
        self.assertGreater(len(encoded),16*1024*1024)
        item={'uri':'test://chart','mimeType':'image/png','blob':encoded}
        parsed=parse_resource_contents({'contents':[item]},'test://chart')
        self.assertEqual(parsed['contents'][0]['blob'],encoded)
        message={'role':'user','content':{'type':'image','mimeType':'image/png','data':encoded}}
        self.assertEqual(parse_prompt_messages({'messages':[message]})['messages'][0]['content']['data'],encoded)

    def test_text_resource_blobs_decode_with_validation(self):
        import base64
        from agentnik.mcp_resources import parse_resource_contents
        def item(mime,data):return {'uri':'test://doc','mimeType':mime,'blob':base64.b64encode(data).decode()}
        for mime in ('text/csv','application/json','application/problem+json','application/xml','application/example+xml','text/plain; charset="UTF-8"'):
            with self.subTest(mime=mime):
                result=parse_resource_contents({'contents':[item(mime,'snow 雪'.encode())]},'test://doc')
                self.assertEqual(result['contents'][0]['text'],'snow 雪');self.assertNotIn('blob',result['contents'][0])
        for invalid in (item('text/plain',b'\xff'),item('text/plain',b'x'*32001),item('text/plain; charset=iso-8859-1',b'x'),item('text/plain; charset=us-ascii','雪'.encode()),dict(item('text/plain',b'x'),blob='!!'),dict(item('text/plain',b'x'),text='duplicate')):
            with self.subTest(invalid=invalid.get('mimeType')),self.assertRaises(ValueError):parse_resource_contents({'contents':[invalid]},'test://doc')

    def test_tool_embedded_text_blob_and_audience(self):
        import base64
        from agentnik.mcp_content import decode_tool_text_resources,model_tool_result,model_images
        def block(text,audience):return {'type':'resource','resource':{'uri':'test://doc','mimeType':'text/plain','blob':base64.b64encode(text.encode()).decode()},'annotations':{'audience':[audience]}}
        result={'content':[block('visible 雪','assistant'),block('private','user')],'structuredContent':{'ok':True}}
        decoded=decode_tool_text_resources(result);visible,user,nontext=model_tool_result(decoded)
        visible,images=model_images(visible,False,0,'test')
        self.assertEqual(visible['content'][0]['resource']['text'],'visible 雪');self.assertEqual(user,['private']);self.assertEqual(nontext,0);self.assertEqual(images,[])
        self.assertEqual(visible['structuredContent'],{'ok':True});self.assertIn('blob',result['content'][0]['resource'])
        bad=block('hello','assistant');bad['resource']['blob']='bad!'
        with self.assertRaises(ValueError):decode_tool_text_resources({'content':[bad]})

    def test_structured_only_tool_result_normalization(self):
        from agentnik.mcp_content import normalize_tool_result,model_tool_result
        from agentnik.mcp_schema import validate_tool_result
        original={'structuredContent':{'count':1}};result=normalize_tool_result(original)
        self.assertEqual(result['content'],[]);self.assertNotIn('content',original);self.assertEqual(model_tool_result(result)[0]['structuredContent'],{'count':1})
        tool={'output_schema_status':'available','output_schema':{'type':'object','properties':{'count':{'type':'integer'}},'required':['count']}}
        self.assertTrue(validate_tool_result(tool,result))
        with self.assertRaises(ValueError):validate_tool_result(tool,normalize_tool_result({'structuredContent':{'count':'bad'}}))
        for invalid in ({},{'structuredContent':[]},{'structuredContent':{},'content':None},{'structuredContent':{},'isError':'yes'}):
            with self.subTest(result=invalid),self.assertRaises(ValueError):normalize_tool_result(invalid)

    def test_tool_audio_is_not_sent_as_text(self):
        from agentnik.mcp_content import model_images
        result={'content':[{'type':'audio','mimeType':'audio/wav','data':'large-base64-audio'}]}
        for enabled in (True,False):
            visible,images=model_images(result,enabled,4,'test')
            self.assertIn('audio content is not supported',visible['content'][0]['text']);self.assertNotIn('large-base64-audio',str(visible));self.assertEqual(images,[])

    def test_local_tool_text_blob_cannot_reflect_mapped_credential(self):
        from PySide6.QtCore import QEventLoop,QTimer
        from PySide6.QtWidgets import QApplication
        from agentnik.mcp_local import LocalSession
        app=QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as folder,patch.dict(os.environ,{'AGENTNIK_TEST_MCP_TOKEN':'secret-fixture-value'}):
            server=Path(folder)/'server.py'
            server.write_text('''import base64,json,os,sys
for line in sys.stdin:
 req=json.loads(line);method=req['method']
 if method=='notifications/initialized':continue
 if method=='initialize':result={'protocolVersion':req['params']['protocolVersion'],'serverInfo':{'name':'test','version':'1'},'capabilities':{'tools':{}}}
 elif method=='tools/list':result={'tools':[{'name':'read','inputSchema':{'type':'object'}}]}
 elif method=='tools/call':result={'content':[{'type':'resource','resource':{'uri':'test://doc','mimeType':'text/plain','blob':base64.b64encode(os.environ['TARGET_TOKEN'].encode()).decode()}}]}
 else:raise RuntimeError('unexpected')
 print(json.dumps({'jsonrpc':'2.0','id':req['id'],'result':result}),flush=True)
''',encoding='utf-8')
            session=LocalSession(sys.executable,[str(server)],env_refs={'TARGET_TOKEN':'AGENTNIK_TEST_MCP_TOKEN'},prefer_modern=False);loop=QEventLoop();out=[]
            session.discovered.connect(lambda info:session.call(info['tool_details'][0],{}));session.called.connect(lambda result:out.append(result));session.ended.connect(lambda result:(out.append(result),loop.quit()));session.start();QTimer.singleShot(5000,loop.quit);loop.exec();session.close()
            self.assertIn('mapped environment value',out[-1]['error']);self.assertNotIn('secret-fixture-value',str(out));self.assertTrue(out[-1]['call_uncertain'])

    def test_local_text_blob_cannot_reflect_mapped_credential(self):
        from PySide6.QtCore import QEventLoop,QTimer
        from PySide6.QtWidgets import QApplication
        from agentnik.mcp_local import LocalSession
        app=QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as folder,patch.dict(os.environ,{'AGENTNIK_TEST_MCP_TOKEN':'secret-fixture-value'}):
            server=Path(folder)/'server.py'
            server.write_text('''import base64,json,os,sys
for line in sys.stdin:
 req=json.loads(line);method=req['method']
 if method=='notifications/initialized':continue
 if method=='initialize':result={'protocolVersion':req['params']['protocolVersion'],'serverInfo':{'name':'test','version':'1'},'capabilities':{'resources':{}}}
 elif method=='resources/list':result={'resources':[{'uri':'test://doc','name':'doc'}]}
 elif method=='resources/read':result={'contents':[{'uri':'test://doc','mimeType':'text/plain','blob':base64.b64encode(os.environ['TARGET_TOKEN'].encode()).decode()}]}
 else:raise RuntimeError('unexpected')
 print(json.dumps({'jsonrpc':'2.0','id':req['id'],'result':result}),flush=True)
''',encoding='utf-8')
            session=LocalSession(sys.executable,[str(server)],env_refs={'TARGET_TOKEN':'AGENTNIK_TEST_MCP_TOKEN'},prefer_modern=False);loop=QEventLoop();out=[]
            def resource(result):
                out.append(result)
                if 'resources' in result:session.read_resource('test://doc')
            session.discovered.connect(lambda _:session.list_resources());session.resources.connect(resource);session.ended.connect(lambda result:(out.append(result),loop.quit()));session.start();QTimer.singleShot(5000,loop.quit);loop.exec();session.close()
            self.assertIn('mapped environment value',out[-1]['error']);self.assertNotIn('secret-fixture-value',str(out))

    def test_tool_resource_links_respect_audience_and_metadata(self):
        from agentnik.mcp_resources import tool_resource_links,merge_resource_links
        result={'content':[{'type':'resource_link','uri':'file:///public','name':'public'},
                           {'type':'resource_link','uri':'file:///private','name':'private','annotations':{'audience':['user']}},
                           {'type':'resource_link','uri':'file:///invalid\n','name':'invalid'},
                           {'type':'resource_link','uri':'file:///public','name':'duplicate'}]}
        links=tool_resource_links(result);self.assertEqual([link['uri'] for link in links],['file:///public'])
        self.assertEqual(merge_resource_links(links,links),links)
        self.assertEqual(tool_resource_links({'content':[{'type':'resource_link','uri':'file:///secret','name':'x','annotations':{'audience':'user'}}]}),[])

    def test_local_tool_resource_link_can_be_read_without_listing(self):
        from PySide6.QtCore import QEventLoop,QTimer
        from PySide6.QtWidgets import QApplication
        from agentnik.mcp_local import LocalSession
        app=QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as folder:
            server=Path(folder)/'linked_resource.py'
            server.write_text('''import json,sys
for line in sys.stdin:
 req=json.loads(line);method=req['method']
 if method=='notifications/initialized':continue
 if method=='initialize':result={'protocolVersion':req['params']['protocolVersion'],'serverInfo':{'name':'Fake','version':'1'},'capabilities':{'tools':{},'resources':{}}}
 elif method=='tools/list':result={'tools':[{'name':'find','inputSchema':{'type':'object'}}]}
 elif method=='tools/call':result={'content':[{'type':'resource_link','uri':'file:///public','name':'public'},{'type':'resource_link','uri':'file:///private','name':'private','annotations':{'audience':['user']}}]}
 elif method=='resources/read':result={'contents':[{'uri':req['params']['uri'],'text':'linked evidence'}]}
 else:raise RuntimeError('unexpected')
 print(json.dumps({'jsonrpc':'2.0','id':req['id'],'result':result}),flush=True)
''',encoding='utf-8')
            session=LocalSession(sys.executable,[str(server)],prefer_modern=False);loop=QEventLoop();out=[]
            def discovered(info):self.assertTrue(session.call(info['tool_details'][0],{}))
            def called(result):
                out.append(result);self.assertFalse(session.read_resource('file:///private'));self.assertFalse(session.read_resource('file:///other'));self.assertTrue(session.read_resource('file:///public'))
            session.discovered.connect(discovered);session.called.connect(called);session.resources.connect(lambda result:(out.append(result),loop.quit()));session.ended.connect(lambda result:(out.append(result),loop.quit()));session.start();QTimer.singleShot(5000,loop.quit);loop.exec();session.close()
            self.assertEqual(out[1]['contents'][0]['text'],'linked evidence')

    def test_remote_session_resource_links_remain_server_scoped(self):
        from unittest.mock import Mock
        from PySide6.QtWidgets import QApplication
        from agentnik.mcp_remote import RemoteSession
        app=QApplication.instance() or QApplication([])
        session=RemoteSession('https://example.com/mcp','',prefer_modern=False);session.result={'call_result':{'content':[{'type':'resource_link','uri':'file:///public','name':'public'},{'type':'resource_link','uri':'file:///private','name':'private','annotations':{'audience':['user']}}]}}
        session.finish_call();session.send=Mock()
        self.assertFalse(session.read_resource('file:///private'));self.assertFalse(session.read_resource('file:///other'));self.assertTrue(session.read_resource('file:///public'))
        self.assertEqual(session.send.call_args.args[0]['params']['uri'],'file:///public');session.timer.stop();session.closed=True

    def test_local_server_image_resource(self):
        import base64
        from test_image_generation import png
        from PySide6.QtCore import QEventLoop,QTimer
        from PySide6.QtWidgets import QApplication
        from agentnik.mcp_local import LocalSession
        app=QApplication.instance() or QApplication([]);encoded=base64.b64encode(png()).decode()
        with tempfile.TemporaryDirectory() as folder:
            server=Path(folder)/'image_resource.py'
            server.write_text('''import json,sys
for line in sys.stdin:
 req=json.loads(line);method=req['method']
 if method=='notifications/initialized':continue
 if method=='initialize':result={'protocolVersion':req['params']['protocolVersion'],'serverInfo':{'name':'Fake','version':'1'},'capabilities':{'resources':{}}}
 elif method=='resources/list':result={'resources':[{'uri':'test://chart','name':'chart','mimeType':'image/png'}]}
 elif method=='resources/read':result={'contents':[{'uri':'test://chart','mimeType':'image/png','blob':sys.argv[1]}]}
 else:raise RuntimeError('unexpected')
 print(json.dumps({'jsonrpc':'2.0','id':req['id'],'result':result}),flush=True)
''',encoding='utf-8')
            session=LocalSession(sys.executable,[str(server),encoded],prefer_modern=False);loop=QEventLoop();out=[]
            def response(result):
                out.append(result)
                if len(out)==1:self.assertTrue(session.read_resource('test://chart'))
                else:loop.quit()
            session.discovered.connect(lambda _:session.list_resources());session.resources.connect(response);session.ended.connect(lambda result:(out.append(result),loop.quit()));session.start();QTimer.singleShot(5000,loop.quit);loop.exec();session.close()
            self.assertEqual(out[1]['contents'][0]['blob'],encoded)

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
                    session=LocalSession(sys.executable,[str(server),mode],prefer_modern=False);loop=QEventLoop();out=[]
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
  pages+=1;result={'tools':[{'name':'query','description':'Original','annotations':{'readOnlyHint':pages==1},'inputSchema':{'type':'object'}}]}
 else:
  pathlib.Path(sys.argv[1]).write_text('called');result={'content':[]}
 print(json.dumps({'jsonrpc':'2.0','id':request['id'],'result':result}),flush=True)
''',encoding='utf-8')
            session=LocalSession(sys.executable,[str(server),str(marker)],prefer_modern=False);loop=QEventLoop();out=[]
            session.discovered.connect(lambda info:session.call(info['tool_details'][0],{}))
            session.ended.connect(lambda result:(out.append(result),loop.quit()))
            session.start();QTimer.singleShot(5000,loop.quit);loop.exec();session.close()
            self.assertIn('definition changed',out[0]['error']);self.assertFalse(out[0]['call_uncertain']);self.assertFalse(marker.exists())

    def test_local_output_schema_changes_block_the_call(self):
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
  pages+=1;result={'tools':[{'name':'query','inputSchema':{'type':'object'},'outputSchema':{'type':'object','required':['one' if pages==1 else 'two']}}]}
 else:
  pathlib.Path(sys.argv[1]).write_text('called');result={'content':[]}
 print(json.dumps({'jsonrpc':'2.0','id':request['id'],'result':result}),flush=True)
''',encoding='utf-8')
            session=LocalSession(sys.executable,[str(server),str(marker)],prefer_modern=False);loop=QEventLoop();out=[]
            session.discovered.connect(lambda info:session.call(info['tool_details'][0],{}));session.ended.connect(lambda result:(out.append(result),loop.quit()))
            session.start();QTimer.singleShot(5000,loop.quit);loop.exec();session.close()
            self.assertIn('definition changed',out[0]['error']);self.assertFalse(out[0]['call_uncertain']);self.assertFalse(marker.exists())

    def test_manager_checks_structured_output_in_worker(self):
        os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
        from PySide6.QtCore import QEventLoop,QTimer
        from PySide6.QtWidgets import QApplication
        from agentnik.ui import Window
        from agentnik.mcp_ui import MCPServers
        app=QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as folder,patch('agentnik.core.discover',return_value={}),patch('agentnik.core.environment_connections',return_value={}):
            store=Store(folder);window=Window(store);dialog=MCPServers(window)
            try:
                dialog.call_tool={'output_schema_status':'available','output_schema':{'type':'object','required':['count']}}
                dialog.show_call_result({'call_result':{'content':[],'structuredContent':{'bad':1}}})
                loop=QEventLoop();timer=QTimer();timer.timeout.connect(lambda:loop.quit() if dialog.validation_job is None else None);timer.start(10);QTimer.singleShot(5000,loop.quit);loop.exec();timer.stop()
                self.assertIsNone(dialog.validation_job);self.assertIn('failed validation',dialog.status.text());self.assertIn('"bad"',dialog.tool_result.toPlainText())
            finally:dialog.close();window.close();app.processEvents();store.db.close()

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
                body=json.loads(self.rfile.read(int(self.headers['Content-Length'])));method=body['method']
                if method=='server/discover':self.send_response(400);self.send_header('Content-Length','0');self.end_headers();return
                calls.append((method,self.headers.get('Mcp-Session-Id')))
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
                body=json.loads(self.rfile.read(int(self.headers['Content-Length'])));method=body['method']
                if method=='server/discover':self.send_response(400);self.send_header('Content-Length','0');self.end_headers();return
                calls.append((method,self.headers.get('Mcp-Session-Id'),self.headers.get('Authorization')))
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
                body=json.loads(self.rfile.read(int(self.headers['Content-Length'])));method=body['method']
                if method=='server/discover':self.send_response(400);self.send_header('Content-Length','0');self.end_headers();return
                calls.append((method,body.get('id'),self.headers.get('Mcp-Session-Id')))
                if method=='notifications/initialized':self.send_response(202);self.end_headers();return
                if method=='initialize':result={'protocolVersion':PROTOCOL,'serverInfo':{'name':'Fake','version':'1'},'capabilities':{'tools':{}}}
                elif method=='tools/list':result={'tools':[{'name':'step','description':'Changed' if state['changed'] else 'Count','inputSchema':{'type':'object'}}]}
                else:state['value']+=1;result={'content':[{'type':'text','text':str(state['value'])}]}
                payload=json.dumps({'jsonrpc':'2.0','id':body['id'],'result':result}).encode();self.send_response(200);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(payload)));self.send_header('Mcp-Session-Id','session-one');self.end_headers();self.wfile.write(payload)
            def do_DELETE(self):
                calls.append(('DELETE',None,self.headers.get('Mcp-Session-Id')));self.send_response(204);self.end_headers()
        app=QApplication.instance() or QApplication([]);server=ThreadingHTTPServer(('127.0.0.1',0),Handler);server_thread=threading.Thread(target=server.serve_forever,daemon=True);server_thread.start()
        config={'mcp_servers':[{'name':'Remote','transport':'http','url':'http://127.0.0.1:'+str(server.server_port)+'/mcp','credential_id':'','enabled':True,'timeout_seconds':180}]};bridge=CodingMCPBridge(config['mcp_servers'][0],config);runtime=Runtime(threading.Event(),Limits());out=[];timeouts=[]
        def work():
            info=bridge.request('discover',{},runtime);timeouts.append(bridge.session.timeout_ms);payload={'tool':info['tool_details'][0],'arguments':{}}
            out.append(bridge.request('call',payload,runtime));out.append(bridge.request('call',payload,runtime));state['changed']=True
            out.append(bridge.request('call',payload,runtime));bridge.close_signal.emit()
        try:
            thread=threading.Thread(target=work);thread.start();loop=QEventLoop();timer=QTimer();timer.timeout.connect(lambda:loop.quit() if not thread.is_alive() and any(item[0]=='DELETE' for item in calls) else None);timer.start(10);QTimer.singleShot(5000,loop.quit);loop.exec();timer.stop();thread.join(1)
            self.assertFalse(thread.is_alive());self.assertEqual(timeouts,[180000]);self.assertEqual([out[0]['call_result']['content'][0]['text'],out[1]['call_result']['content'][0]['text']],['1','2'])
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
                body=json.loads(self.rfile.read(int(self.headers['Content-Length'])));method=body['method']
                if method=='server/discover':self.send_response(400);self.send_header('Content-Length','0');self.end_headers();return
                calls.append(method)
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
 if method=='server/discover':print(json.dumps({'jsonrpc':'2.0','id':request['id'],'error':{'code':-32601,'message':'unsupported'}}),flush=True);continue
 if method=='notifications/initialized':continue
 if method=='initialize':result={'protocolVersion':request['params']['protocolVersion'],'serverInfo':{'name':'Fake' if os.environ.get('TARGET_TOKEN')=='snapshot-unique-value' else 'Incorrect','version':os.getcwd()},'capabilities':{'tools':{}}}
 elif method=='tools/list':result={'tools':[{'name':'query','inputSchema':{'type':'object'}}]}
 else:result={'content':[{'type':'text','text':'ok'}]}
 print(json.dumps({'jsonrpc':'2.0','id':request['id'],'result':result}),flush=True)
''',encoding='utf-8')
            config={'mcp_servers':[{'name':'Fake','command':sys.executable,'args':[str(server)],'env':{'TARGET_TOKEN':'AGENTNIK_MCP_TEST_SOURCE'},'enabled':True,'timeout_seconds':180,'working_directory':folder}]};bridge=CodingMCPBridge(config['mcp_servers'][0],config)
            os.environ['AGENTNIK_MCP_TEST_SOURCE']='changed-after-snapshot'
            runtime=Runtime(threading.Event(),Limits());out=[];timeouts=[]
            def work():
                info=bridge.request('discover',{},runtime);out.append(info);timeouts.append(bridge.session.timeout_ms)
                out.append(bridge.request('call',{'tool':info['tool_details'][0],'arguments':{}},runtime))
                config['mcp_servers']=[]
                out.append(bridge.request('call',{'tool':info['tool_details'][0],'arguments':{}},runtime));bridge.close_signal.emit()
            thread=threading.Thread(target=work);thread.start();loop=QEventLoop();timer=QTimer();timer.timeout.connect(lambda:loop.quit() if not thread.is_alive() else None);timer.start(10);QTimer.singleShot(5000,loop.quit);loop.exec();timer.stop();thread.join(1);app.processEvents()
            self.assertFalse(thread.is_alive());self.assertEqual(Path(out[0]['version']).resolve(),Path(folder).resolve());self.assertEqual(timeouts,[180000]);self.assertEqual(out[1]['call_result']['content'][0]['text'],'ok');self.assertIn('changed',out[2]['error']);self.assertTrue(bridge.closed)

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
                dialog=MCPServers(window);dialog.transport.setCurrentIndex(1);dialog.name.setText('Remote');dialog.url.setText('https://example.com/mcp');dialog.token.setText('secret-test-token');dialog.timeout.setValue(240)
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
                dialog.tool_args.setPlainText('{"query":"MCP"}')
                with patch.object(QDialog,'exec',return_value=QDialog.DialogCode.Accepted) as review,patch('agentnik.mcp_remote.RemoteProbe') as remote:
                    dialog.call_remote();wait_validation();remote.assert_called_once()
                    review.assert_not_called()
                    self.assertEqual(remote.call_args.kwargs['invocation']['arguments'],{'query':'MCP'});self.assertEqual(remote.call_args.kwargs['timeout_seconds'],240);remote.return_value.start.assert_called_once()
                    dialog.remote=None
                dialog.close()
            finally:window.close();app.processEvents();store.db.close()
