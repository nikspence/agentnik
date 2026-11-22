import json
import sys
import threading
import unittest
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path

from PySide6.QtCore import QEventLoop,QTimer
from PySide6.QtWidgets import QApplication
from agentnik.mcp_local import LocalSession
from agentnik.mcp_remote import RemoteSession


class TaskInputTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.app=QApplication.instance() or QApplication([])

    def test_task_association_cannot_be_used_outside_an_active_task(self):
        from agentnik.mcp_elicitation import input_task_metadata
        params={'_meta':{'io.modelcontextprotocol/related-task':{'taskId':'task-1'}}}
        for task_id,active in ((None,False),('task-1',False),('other',True),(None,True)):
            with self.subTest(task_id=task_id,active=active),self.assertRaises(ValueError):input_task_metadata(params,task_id,active)
        self.assertIsNone(input_task_metadata({},None,False))

    def run_session(self,session,expected_input):
        session.elicitation_enabled=True;loop=QEventLoop();output=[];forms=[]
        session.discovered.connect(lambda info:session.call(info['tool_details'][0],{}))
        def requested(value):
            forms.append(value);self.assertFalse(session.timer.isActive())
            QTimer.singleShot(10,lambda:session.continue_elicitation({'request':{'action':'accept','content':{'choice':'yes'}}}))
        session.elicitation_requested.connect(requested)
        session.called.connect(lambda value:(output.append(value),loop.quit()));session.ended.connect(lambda value:(output.append(value),loop.quit()))
        timer=QTimer();timer.setSingleShot(True);timer.timeout.connect(loop.quit);timer.start(8000);session.start();loop.exec();timer.stop()
        self.assertTrue(output);self.assertIn('call_result',output[0],str(output));self.assertEqual(output[0]['call_result']['content'][0]['text'],'done');self.assertEqual(len(forms),expected_input)

    def test_local_task_input_requires_matching_task(self):
        path=Path(__file__).parent/'fixtures'/'mcp_legacy_task_input.py'
        for mode in ('matching','mismatch'):
            with self.subTest(mode=mode):
                session=LocalSession(sys.executable,['-u',str(path),mode],timeout_seconds=5,prefer_modern=False)
                try:self.run_session(session,mode=='matching')
                finally:session.close()

    def test_remote_task_input_on_response_and_standalone_streams(self):
        for stream,mode in (('response','matching'),('standalone','matching'),('response','mismatch'),('standalone','mismatch')):
            with self.subTest(stream=stream,mode=mode):
                started=threading.Event();answered=threading.Event();received=[]
                class Handler(BaseHTTPRequestHandler):
                    def log_message(self,*args):pass
                    def do_POST(self):
                        body=json.loads(self.rfile.read(int(self.headers['Content-Length'])));method=body.get('method')
                        if method is None:received.append(body);self.send_response(202);self.end_headers();answered.set();return
                        if method=='notifications/initialized':self.send_response(202);self.end_headers();return
                        if method=='initialize':result={'protocolVersion':'2025-11-25','serverInfo':{'name':'Fixture','version':'1'},'capabilities':{'tools':{},'tasks':{'requests':{'tools':{'call':{}}}}}}
                        elif method=='tools/list':result={'tools':[{'name':'work','inputSchema':{'type':'object'},'execution':{'taskSupport':'required'}}]}
                        elif method=='tools/call':result={'task':{'taskId':'task-1','status':'working','createdAt':'2026-01-01T00:00:00Z','lastUpdatedAt':'2026-01-01T00:00:00Z','ttl':None}}
                        elif method=='tasks/result':
                            self.send_response(200);self.send_header('Content-Type','text/event-stream');self.end_headers()
                            if stream=='response':self.wfile.write(b'data: '+json.dumps(self.input_request()).encode()+b'\n\n');self.wfile.flush()
                            else:started.set()
                            if answered.wait(5):
                                result={'content':[{'type':'text','text':'done'}],'_meta':{'io.modelcontextprotocol/related-task':{'taskId':'task-1'}}}
                                self.wfile.write(b'data: '+json.dumps({'jsonrpc':'2.0','id':body['id'],'result':result}).encode()+b'\n\n');self.wfile.flush()
                            return
                        else:raise AssertionError(method)
                        payload=json.dumps({'jsonrpc':'2.0','id':body['id'],'result':result}).encode();self.send_response(200);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(payload)));self.send_header('Mcp-Session-Id','fixture');self.end_headers();self.wfile.write(payload)
                    def input_request(self):return {'jsonrpc':'2.0','id':'input','method':'elicitation/create','params':{'message':'Choose','requestedSchema':{'type':'object','properties':{'choice':{'type':'string'}},'required':['choice']},'_meta':{'io.modelcontextprotocol/related-task':{'taskId':'other' if mode=='mismatch' else 'task-1'}}}}
                    def do_GET(self):
                        if stream=='response':self.send_response(405);self.end_headers();return
                        self.send_response(200);self.send_header('Content-Type','text/event-stream');self.end_headers();self.wfile.write(b': ready\n\n');self.wfile.flush()
                        if started.wait(5):self.wfile.write(b'data: '+json.dumps(self.input_request()).encode()+b'\n\n');self.wfile.flush();answered.wait(5)
                    def do_DELETE(self):self.send_response(204);self.end_headers()
                server=ThreadingHTTPServer(('127.0.0.1',0),Handler);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
                session=RemoteSession('http://127.0.0.1:'+str(server.server_port)+'/mcp','',timeout_seconds=5,prefer_modern=False)
                try:
                    self.run_session(session,mode=='matching')
                    if mode=='matching':self.assertEqual(received[0]['result'],{'action':'accept','content':{'choice':'yes'},'_meta':{'io.modelcontextprotocol/related-task':{'taskId':'task-1'}}})
                    else:self.assertEqual(received[0]['error']['code'],-32602)
                finally:started.set();answered.set();session.shutdown();server.shutdown();server.server_close();thread.join(2)
