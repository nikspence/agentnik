import json
import threading
import unittest
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from PySide6.QtCore import QEventLoop,QTimer
from PySide6.QtWidgets import QApplication
from agentnik.mcp_remote import RemoteSession


class RemoteNegotiationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.app=QApplication.instance() or QApplication([])

    def exercise(self,mode):
        calls=[]
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def do_POST(self):
                request=json.loads(self.rfile.read(int(self.headers['Content-Length'])));method=request['method'];calls.append((method,dict(self.headers)))
                if method=='notifications/initialized':self.send_response(202);self.end_headers();return
                if method=='server/discover':
                    if mode in ('400','404','405','401','403','429','500'):
                        self.send_response(int(mode));self.send_header('Content-Length','0');self.end_headers();return
                    if mode in ('legacy_error','modern_error','modern_http_error','reflected_token'):
                        error={'code':-32601 if mode in ('legacy_error','reflected_token') else -32022,'message':'synthetic-token' if mode=='reflected_token' else 'private diagnostic','data':{'secret':'private'}}
                        payload=json.dumps({'jsonrpc':'2.0','id':request['id'],'error':error}).encode();self.send_response(400 if mode in ('modern_http_error','reflected_token') else 200);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(payload)));self.end_headers();self.wfile.write(payload);return
                    result={'supportedVersions':['2026-07-28','2025-11-25'],'capabilities':{}}
                elif method=='initialize':result={'protocolVersion':'2025-11-25','serverInfo':{'name':'Legacy','version':'1'},'capabilities':{}}
                else:raise AssertionError(method)
                payload=json.dumps({'jsonrpc':'2.0','id':request['id'],'result':result}).encode();self.send_response(200);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(payload)));self.end_headers();self.wfile.write(payload)
            def do_GET(self):self.send_response(405);self.end_headers()
        server=ThreadingHTTPServer(('127.0.0.1',0),Handler);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        session=RemoteSession('http://127.0.0.1:'+str(server.server_port)+'/mcp','synthetic-token',timeout_seconds=5);loop=QEventLoop();out=[]
        session.discovered.connect(lambda value:(out.append(value),loop.quit()));session.ended.connect(lambda value:(out.append(value),loop.quit()))
        timer=QTimer();timer.setSingleShot(True);timer.timeout.connect(loop.quit);timer.start(7000);session.start()
        try:loop.exec();timer.stop();self.assertTrue(out);return out[0],calls
        finally:session.shutdown();server.shutdown();server.server_close();thread.join(2)

    def test_dual_era_server_uses_modern(self):
        result,calls=self.exercise('modern');self.assertEqual(result['protocol'],'2026-07-28');self.assertEqual([item[0] for item in calls],['server/discover'])
        headers={key.lower():value for key,value in calls[0][1].items()};self.assertEqual(headers['mcp-method'],'server/discover');self.assertEqual(headers['mcp-protocol-version'],'2026-07-28');self.assertEqual(headers['authorization'],'Bearer synthetic-token')

    def test_legacy_rejections_fall_back_once(self):
        for mode in ('400','404','405','legacy_error'):
            with self.subTest(mode=mode):
                result,calls=self.exercise(mode);self.assertEqual(result['protocol'],'2025-11-25');self.assertEqual([item[0] for item in calls],['server/discover','initialize','notifications/initialized'])

    def test_modern_and_transport_errors_do_not_fall_back(self):
        for mode in ('401','403','429','500','modern_error','modern_http_error','reflected_token'):
            with self.subTest(mode=mode):
                result,calls=self.exercise(mode);self.assertIn('error',result);self.assertEqual([item[0] for item in calls],['server/discover']);self.assertNotIn('private',str(result));self.assertNotIn('synthetic-token',str(result))
