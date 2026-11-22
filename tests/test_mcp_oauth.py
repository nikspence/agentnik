import unittest

from agentnik.mcp_oauth import bearer_challenge,protected_resource_metadata_urls,authorization_server_metadata_urls


class MCPOAuthDiscovery(unittest.TestCase):
    def test_remote_authentication_failures_are_actionable_and_do_not_echo_server_text(self):
        import json,threading
        from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
        from PySide6.QtCore import QEventLoop,QTimer
        from PySide6.QtWidgets import QApplication
        from agentnik.mcp_remote import RemoteSession
        from agentnik.mcp_support import PROTOCOL
        app=QApplication.instance() or QApplication([])
        for mode in ('unauthorized','insufficient'):
            with self.subTest(mode=mode):
                calls=[]
                class Handler(BaseHTTPRequestHandler):
                    def log_message(self,*args):pass
                    def do_POST(self,mode=mode,calls=calls):
                        body=json.loads(self.rfile.read(int(self.headers['Content-Length'])));method=body['method'];calls.append(method)
                        if method=='notifications/initialized':self.send_response(202);self.end_headers();return
                        if mode=='unauthorized' and method=='initialize' or mode=='insufficient' and method=='tools/call':
                            self.send_response(401 if mode=='unauthorized' else 403);self.send_header('WWW-Authenticate','Bearer error="insufficient_scope", scope="private:scope"');self.end_headers();return
                        result={'protocolVersion':PROTOCOL,'serverInfo':{'name':'Fixture','version':'1'},'capabilities':{'tools':{}}} if method=='initialize' else {'tools':[{'name':'work','inputSchema':{'type':'object'}}]}
                        payload=json.dumps({'jsonrpc':'2.0','id':body['id'],'result':result}).encode();self.send_response(200);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(payload)));self.send_header('Mcp-Session-Id','session-one');self.end_headers();self.wfile.write(payload)
                    def do_GET(self):self.send_response(405);self.end_headers()
                    def do_DELETE(self):self.send_response(204);self.end_headers()
                server=ThreadingHTTPServer(('127.0.0.1',0),Handler);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
                session=RemoteSession('http://127.0.0.1:'+str(server.server_port)+'/mcp','',timeout_seconds=3);loop=QEventLoop();out=[]
                session.discovered.connect(lambda info:session.call(info['tool_details'][0],{}));session.ended.connect(lambda error:(out.append(error),loop.quit()));session.start();timer=QTimer();timer.setSingleShot(True);timer.timeout.connect(loop.quit);timer.start(5000)
                try:
                    loop.exec();timer.stop();self.assertTrue(out);self.assertIn('OAuth sign-in is not yet supported',out[0]['error']);self.assertNotIn('private:scope',out[0]['error'])
                    self.assertEqual(out[0]['call_uncertain'],mode=='insufficient')
                    if mode=='insufficient':self.assertEqual(calls.count('tools/call'),1);self.assertIn('insufficient scope',out[0]['error'])
                    else:self.assertIn('valid bearer token',out[0]['error'])
                finally:session.shutdown();server.shutdown();server.server_close();thread.join(2)

    def test_bearer_challenges_are_parsed_without_confusing_other_schemes(self):
        header='Basic realm="legacy", Bearer resource_metadata="https://auth.example/metadata", scope="read write", error="insufficient_scope"'
        self.assertEqual(bearer_challenge(header),{'resource_metadata':'https://auth.example/metadata','scope':'read write','error':'insufficient_scope'})
        self.assertEqual(bearer_challenge('Bearer scope = "one,two", error="invalid_token"'),{'scope':'one,two','error':'invalid_token'})
        self.assertEqual(bearer_challenge('Basic realm="legacy", Bearer'),{})
        self.assertIsNone(bearer_challenge('Basic realm="example"'))
        for invalid in ('Bearer error="a", error="b"','Bearer scope="one", Bearer scope="two"','Bearer scope="unterminated','Bearer error="x\r\nInjected: y"'):
            with self.subTest(invalid=invalid):self.assertIsNone(bearer_challenge(invalid))

    def test_protected_resource_metadata_priority_and_path(self):
        self.assertEqual(protected_resource_metadata_urls('https://mcp.example/mcp/deep?tools=one'),['https://mcp.example/.well-known/oauth-protected-resource/mcp/deep','https://mcp.example/.well-known/oauth-protected-resource'])
        self.assertEqual(protected_resource_metadata_urls('https://mcp.example/'),['https://mcp.example/.well-known/oauth-protected-resource'])
        self.assertEqual(protected_resource_metadata_urls('https://mcp.example/mcp/'),['https://mcp.example/.well-known/oauth-protected-resource/mcp/','https://mcp.example/.well-known/oauth-protected-resource'])
        self.assertEqual(protected_resource_metadata_urls('https://mcp.example/mcp',{'resource_metadata':'https://auth.example/metadata?version=1'}),['https://auth.example/metadata?version=1'])
        for invalid in ('http://example/mcp','https://user:password@example/mcp','https://example/mcp#fragment','https://example:bad/mcp'):
            with self.subTest(invalid=invalid),self.assertRaises(ValueError):protected_resource_metadata_urls(invalid)
        with self.assertRaises(ValueError):protected_resource_metadata_urls('https://mcp.example/mcp',{'resource_metadata':'http://insecure.example/metadata'})

    def test_authorization_server_metadata_candidates(self):
        self.assertEqual(authorization_server_metadata_urls('https://auth.example/tenant'),['https://auth.example/.well-known/oauth-authorization-server/tenant','https://auth.example/.well-known/openid-configuration/tenant','https://auth.example/tenant/.well-known/openid-configuration'])
        self.assertEqual(authorization_server_metadata_urls('https://auth.example/'),['https://auth.example/.well-known/oauth-authorization-server','https://auth.example/.well-known/openid-configuration'])
        self.assertEqual(authorization_server_metadata_urls('https://auth.example/tenant/')[-1],'https://auth.example/tenant/.well-known/openid-configuration')
        for invalid in ('http://auth.example','https://auth.example/path?x=1','https://auth.example/#fragment','https://a@auth.example/'):
            with self.subTest(invalid=invalid),self.assertRaises(ValueError):authorization_server_metadata_urls(invalid)


if __name__=='__main__':unittest.main()
