import unittest

from agentnik.mcp_oauth import bearer_challenge,protected_resource_metadata_urls,authorization_server_metadata_urls


class MCPOAuthDiscovery(unittest.TestCase):
    def test_authorization_pkce_state_and_token_exchange(self):
        import base64,hashlib,json,threading
        from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
        from urllib.parse import parse_qs,urlencode,urlsplit
        from PySide6.QtCore import QEventLoop,QTimer,QUrl
        from PySide6.QtNetwork import QNetworkAccessManager,QNetworkRequest,QSsl
        from PySide6.QtWidgets import QApplication
        from agentnik.mcp_oauth_flow import OAuthAuthorization
        app=QApplication.instance() or QApplication([]);received=[];browsed=[];replies=[];callback_manager=QNetworkAccessManager()
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def do_POST(self):
                body=self.rfile.read(int(self.headers['Content-Length']));received.append((self.path,parse_qs(body.decode()),self.headers.get('Cookie'),self.headers.get('Authorization')))
                payload=json.dumps({'access_token':'synthetic-access','refresh_token':'synthetic-refresh','token_type':'Bearer','expires_in':600}).encode();self.send_response(200);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(payload)));self.end_headers();self.wfile.write(payload)
        server=ThreadingHTTPServer(('127.0.0.1',0),Handler);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start();base='https://127.0.0.1:'+str(server.server_port)
        class LoopbackManager:
            def __init__(self):self.manager=QNetworkAccessManager()
            def post(self,request,data):
                assert request.attribute(QNetworkRequest.Attribute.RedirectPolicyAttribute)==QNetworkRequest.RedirectPolicy.ManualRedirectPolicy
                assert request.sslConfiguration().protocol() in (QSsl.SslProtocol.TlsV1_2,QSsl.SslProtocol.TlsV1_2OrLater,QSsl.SslProtocol.TlsV1_3,QSsl.SslProtocol.TlsV1_3OrLater)
                replacement=QNetworkRequest(request);url=QUrl(request.url());url.setScheme('http');replacement.setUrl(url);return self.manager.post(replacement,data)
        def open_url(url):
            browsed.append(url.toString());params=parse_qs(urlsplit(browsed[0]).query);redirect=params['redirect_uri'][0];state=params['state'][0]
            def send(values):
                reply=callback_manager.get(QNetworkRequest(QUrl(redirect+'?'+urlencode(values))));replies.append(reply)
            QTimer.singleShot(0,lambda:send({'code':'synthetic-code','state':'wrong'}))
            QTimer.singleShot(50,lambda:send({'code':'synthetic-code','state':'한글'}))
            QTimer.singleShot(100,lambda:send({'code':'synthetic-code','state':state,'iss':base+'/issuer'}))
            return True
        metadata={'issuer':base+'/issuer','authorization_endpoint':base+'/authorize?existing=value','token_endpoint':base+'/token','pkce_s256':True}
        manager=LoopbackManager();job=OAuthAuthorization(base+'/mcp?tools=selected',metadata,'public-client','read write',manager=manager,open_url=open_url,timeout_ms=5000);loop=QEventLoop();out=[];job.finished.connect(lambda value:(out.append(value),loop.quit()));timer=QTimer();timer.setSingleShot(True);timer.timeout.connect(loop.quit);timer.start(7000);job.start()
        try:
            loop.exec();timer.stop();self.assertEqual(out,[{'access_token':'synthetic-access','refresh_token':'synthetic-refresh','expires_in':600}]);self.assertEqual(len(received),1)
            sent=received[0][1];auth=parse_qs(urlsplit(browsed[0]).query)
            self.assertEqual(sent['code'],['synthetic-code']);self.assertEqual(sent['client_id'],['public-client']);self.assertEqual(sent['resource'],[base+'/mcp?tools=selected']);self.assertEqual(auth['resource'],sent['resource']);self.assertEqual(auth['scope'],['read write']);self.assertEqual(auth['code_challenge_method'],['S256'])
            expected=base64.urlsafe_b64encode(hashlib.sha256(sent['code_verifier'][0].encode()).digest()).rstrip(b'=').decode();self.assertEqual(auth['code_challenge'],[expected]);self.assertIsNone(received[0][2]);self.assertIsNone(received[0][3]);self.assertEqual(len(replies),3)
        finally:job.stop();server.shutdown();server.server_close();thread.join(2)

    def test_authorization_refuses_unsafe_settings_and_clears_secrets_on_cancel(self):
        from PySide6.QtWidgets import QApplication
        from agentnik.mcp_oauth_flow import OAuthAuthorization
        app=QApplication.instance() or QApplication([]);base={'issuer':'https://auth.example','authorization_endpoint':'https://auth.example/authorize','token_endpoint':'https://auth.example/token','pkce_s256':True}
        for metadata in (dict(base,pkce_s256=False),dict(base,token_endpoint='http://bad.example/token'),dict(base,authorization_endpoint='https://auth.example/authorize?state=forged')):
            out=[];job=OAuthAuthorization('https://mcp.example/mcp',metadata,'client',open_url=lambda _:True);job.finished.connect(out.append);job.start();self.assertIn('error',out[0]);self.assertEqual(job.verifier,'');self.assertFalse(job.listener.isListening())
        job=OAuthAuthorization('https://mcp.example/mcp',base,'client',open_url=lambda _:True);out=[];job.finished.connect(out.append);job.start();self.assertTrue(job.listener.isListening());self.assertTrue(job.verifier);job.stop();self.assertEqual(job.verifier,'');self.assertEqual(job.state,'');self.assertFalse(job.listener.isListening());self.assertIn('error',out[0])
        out=[];job=OAuthAuthorization('https://mcp.example/mcp',base,'client','read\r\nwrite',open_url=lambda _:True);job.finished.connect(out.append);job.start();self.assertIn('error',out[0])

    def test_token_exchange_rejects_redirects_and_invalid_responses(self):
        import json,threading
        from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
        from urllib.parse import parse_qs,urlencode,urlsplit
        from PySide6.QtCore import QEventLoop,QTimer,QUrl
        from PySide6.QtNetwork import QNetworkAccessManager,QNetworkRequest
        from PySide6.QtWidgets import QApplication
        from agentnik.mcp_oauth_flow import OAuthAuthorization
        app=QApplication.instance() or QApplication([])
        for mode in ('redirect','wrong-type','duplicate','oversize'):
            with self.subTest(mode=mode):
                calls=[];callbacks=[];callback_manager=QNetworkAccessManager()
                class Handler(BaseHTTPRequestHandler):
                    def log_message(self,*args):pass
                    def do_POST(self,mode=mode,calls=calls):
                        self.rfile.read(int(self.headers['Content-Length']));calls.append(self.path)
                        if mode=='redirect':self.send_response(302);self.send_header('Location','https://attacker.invalid/token');self.end_headers();return
                        payload=(b' '*65537 if mode=='oversize' else b'{"token_type":"Bearer","access_token":"x","access_token":"y"}' if mode=='duplicate' else json.dumps({'token_type':'Basic','access_token':'private-value'}).encode())
                        try:self.send_response(200);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(payload)));self.end_headers();self.wfile.write(payload)
                        except (BrokenPipeError,ConnectionResetError,ConnectionAbortedError):pass
                server=ThreadingHTTPServer(('127.0.0.1',0),Handler);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start();base='https://127.0.0.1:'+str(server.server_port)
                class LoopbackManager:
                    def __init__(self):self.manager=QNetworkAccessManager()
                    def post(self,request,data):
                        replacement=QNetworkRequest(request);url=QUrl(request.url());url.setScheme('http');replacement.setUrl(url);return self.manager.post(replacement,data)
                def open_url(value):
                    params=parse_qs(urlsplit(value.toString()).query)
                    QTimer.singleShot(0,lambda:callbacks.append(callback_manager.get(QNetworkRequest(QUrl(params['redirect_uri'][0]+'?'+urlencode({'code':'code','state':params['state'][0]}))))))
                    return True
                metadata={'issuer':base+'/issuer','authorization_endpoint':base+'/authorize','token_endpoint':base+'/token','pkce_s256':True};manager=LoopbackManager();job=OAuthAuthorization(base+'/mcp',metadata,'client',manager=manager,open_url=open_url,timeout_ms=3000);loop=QEventLoop();out=[];job.finished.connect(lambda value:(out.append(value),loop.quit()));timer=QTimer();timer.setSingleShot(True);timer.timeout.connect(loop.quit);timer.start(5000);job.start()
                try:
                    loop.exec();timer.stop();self.assertTrue(out);self.assertIn('error',out[0]);self.assertNotIn('private-value',str(out));self.assertEqual(calls,['/token']);self.assertEqual(job.verifier,'');self.assertEqual(job.state,'')
                finally:job.stop();server.shutdown();server.server_close();thread.join(2)

    def test_metadata_validation_checks_resource_issuer_and_pkce(self):
        from agentnik.mcp_oauth_discovery import parse_resource_metadata,parse_authorization_metadata
        resource='https://mcp.example/team/mcp';issuer='https://auth.example/tenant'
        self.assertEqual(parse_resource_metadata({'resource':'https://mcp.example/team','authorization_servers':[issuer]},resource)['issuers'],[issuer])
        for claimed in ('https://attacker.example/team','https://mcp.example/te','https://mcp.example/other'):
            with self.subTest(claimed=claimed),self.assertRaises(ValueError):parse_resource_metadata({'resource':claimed,'authorization_servers':[issuer]},resource)
        meta={'issuer':issuer,'authorization_endpoint':'https://auth.example/authorize','token_endpoint':'https://auth.example/token','code_challenge_methods_supported':['S256']}
        self.assertTrue(parse_authorization_metadata(meta,issuer)['pkce_s256'])
        with self.assertRaises(ValueError):parse_authorization_metadata(dict(meta,issuer='https://attacker.example'),issuer)
        with self.assertRaises(ValueError):parse_authorization_metadata(dict(meta,token_endpoint='http://insecure.example'),issuer)
        self.assertFalse(parse_authorization_metadata(dict(meta,code_challenge_methods_supported=[]),issuer)['pkce_s256'])

    def test_async_metadata_discovery_fallback_and_no_credentials(self):
        import json,threading
        from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
        from PySide6.QtCore import QEventLoop,QTimer,QUrl
        from PySide6.QtNetwork import QNetworkAccessManager,QNetworkRequest
        from PySide6.QtWidgets import QApplication
        from agentnik.mcp_oauth_discovery import OAuthMetadataDiscovery
        app=QApplication.instance() or QApplication([]);requests=[];base=[None]
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def do_GET(self):
                requests.append((self.path,self.headers.get('Authorization'),self.headers.get('Cookie')))
                if self.path in ('/.well-known/oauth-protected-resource/mcp','/.well-known/oauth-authorization-server/tenant'):
                    self.send_response(404);self.end_headers();return
                if self.path=='/.well-known/oauth-protected-resource':document={'resource':base[0]+'/mcp','authorization_servers':[base[0]+'/tenant']}
                elif self.path=='/.well-known/openid-configuration/tenant':document={'issuer':base[0]+'/tenant','authorization_endpoint':base[0]+'/authorize','token_endpoint':base[0]+'/token','code_challenge_methods_supported':['S256']}
                else:self.send_response(500);self.end_headers();return
                payload=json.dumps(document).encode();self.send_response(200);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(payload)));self.end_headers();self.wfile.write(payload)
        server=ThreadingHTTPServer(('127.0.0.1',0),Handler);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start();base[0]='https://127.0.0.1:'+str(server.server_port)
        class LoopbackManager:
            def __init__(self):self.manager=QNetworkAccessManager();self.urls=[]
            def get(self,request):
                self.urls.append(request.url().toString());self.assert_request(request)
                replacement=QNetworkRequest(request);url=QUrl(request.url());url.setScheme('http');replacement.setUrl(url);return self.manager.get(replacement)
            def assert_request(self,request):
                assert request.attribute(QNetworkRequest.Attribute.RedirectPolicyAttribute)==QNetworkRequest.RedirectPolicy.ManualRedirectPolicy
                assert not request.rawHeader('Authorization')
        manager=LoopbackManager();job=OAuthMetadataDiscovery(base[0]+'/mcp',manager=manager);loop=QEventLoop();out=[];job.finished.connect(lambda value:(out.append(value),loop.quit()));timer=QTimer();timer.setSingleShot(True);timer.timeout.connect(loop.quit);timer.start(5000);job.start()
        try:
            loop.exec();timer.stop();self.assertTrue(out);self.assertNotIn('error',out[0]);self.assertTrue(out[0]['authorization_server']['pkce_s256'])
            self.assertEqual([r[0] for r in requests],['/.well-known/oauth-protected-resource/mcp','/.well-known/oauth-protected-resource','/.well-known/oauth-authorization-server/tenant','/.well-known/openid-configuration/tenant'])
            self.assertTrue(all(auth is None and cookie is None for _,auth,cookie in requests));self.assertTrue(all(url.startswith('https://') for url in manager.urls))
        finally:job.stop();server.shutdown();server.server_close();thread.join(2)

    def test_async_discovery_honors_challenge_and_rejects_unsafe_responses(self):
        import json,threading
        from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
        from PySide6.QtCore import QEventLoop,QTimer,QUrl
        from PySide6.QtNetwork import QNetworkAccessManager,QNetworkRequest,QSsl
        from PySide6.QtWidgets import QApplication
        from agentnik.mcp_oauth_discovery import OAuthMetadataDiscovery
        app=QApplication.instance() or QApplication([])
        for mode in ('challenge','redirect','invalid','oversize'):
            with self.subTest(mode=mode):
                calls=[];base=[None]
                class Handler(BaseHTTPRequestHandler):
                    def log_message(self,*args):pass
                    def do_GET(self,mode=mode,calls=calls,base=base):
                        calls.append(self.path)
                        if mode=='redirect':self.send_response(302);self.send_header('Location','https://attacker.invalid/metadata');self.end_headers();return
                        if mode=='oversize':payload=b' '*131073
                        elif self.path=='/hint':payload=json.dumps({'resource':('https://attacker.invalid/mcp' if mode=='invalid' else base[0]+'/mcp'),'authorization_servers':[base[0]+'/issuer']}).encode()
                        else:payload=json.dumps({'issuer':base[0]+'/issuer','authorization_endpoint':base[0]+'/authorize','token_endpoint':base[0]+'/token','code_challenge_methods_supported':['S256']}).encode()
                        try:self.send_response(200);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(payload)));self.end_headers();self.wfile.write(payload)
                        except (BrokenPipeError,ConnectionResetError,ConnectionAbortedError):pass
                server=ThreadingHTTPServer(('127.0.0.1',0),Handler);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start();base[0]='https://127.0.0.1:'+str(server.server_port)
                class LoopbackManager:
                    def __init__(self):self.manager=QNetworkAccessManager()
                    def get(self,request):
                        assert request.sslConfiguration().protocol() in (QSsl.SslProtocol.TlsV1_2,QSsl.SslProtocol.TlsV1_2OrLater,QSsl.SslProtocol.TlsV1_3,QSsl.SslProtocol.TlsV1_3OrLater)
                        replacement=QNetworkRequest(request);url=QUrl(request.url());url.setScheme('http');replacement.setUrl(url);return self.manager.get(replacement)
                manager=LoopbackManager();job=OAuthMetadataDiscovery(base[0]+'/mcp',{'resource_metadata':base[0]+'/hint'},manager=manager);loop=QEventLoop();out=[];job.finished.connect(lambda value:(out.append(value),loop.quit()));timer=QTimer();timer.setSingleShot(True);timer.timeout.connect(loop.quit);timer.start(5000);job.start()
                try:
                    loop.exec();timer.stop();self.assertTrue(out);self.assertEqual(calls[0],'/hint')
                    if mode=='challenge':self.assertNotIn('error',out[0]);self.assertEqual(calls[1],'/.well-known/oauth-authorization-server/issuer')
                    else:self.assertIn('error',out[0]);self.assertEqual(calls,['/hint'])
                finally:job.stop();server.shutdown();server.server_close();thread.join(2)

    def test_settings_discovery_uses_only_matching_challenge_and_cancels_on_selection_change(self):
        import tempfile
        from unittest.mock import Mock,patch
        from PySide6.QtCore import QObject,Signal
        from PySide6.QtWidgets import QApplication
        from agentnik.mcp_ui import MCPServers
        from agentnik.storage import Store
        from agentnik.ui import Window
        from agentnik import core
        app=QApplication.instance() or QApplication([]);created=[]
        class FakeDiscovery(QObject):
            finished=Signal(object)
            def __init__(self,url,challenge,parent,timeout_ms):super().__init__(parent);self.url=url;self.challenge=challenge;self.stopped=False;created.append(self)
            def start(self):pass
            def stop(self):self.stopped=True;self.finished.emit({'error':'cancelled'})
        with tempfile.TemporaryDirectory() as folder,patch.object(core,'discover',return_value={}),patch.object(core,'environment_connections',return_value={}),patch('agentnik.mcp_oauth_discovery.OAuthMetadataDiscovery',FakeDiscovery):
            store=Store(folder);store.config['mcp_servers']=[{'name':'Remote','transport':'http','url':'https://example.com/mcp','credential_id':'','enabled':True}];store.flush();window=Window(store);dialog=MCPServers(window)
            try:
                dialog.list.setCurrentRow(0);dialog.oauth_challenge={'resource_metadata':'https://example.com/hint'};dialog.oauth_challenge_url='https://other.example/mcp';dialog.discover_oauth();self.assertIsNone(created[-1].challenge)
                dialog.list.setCurrentRow(-1);self.assertTrue(created[-1].stopped);self.assertIsNone(dialog.oauth_discovery)
                dialog.list.setCurrentRow(0);probe=Mock();probe.oauth_challenge={'resource_metadata':'https://example.com/hint'};dialog.remote=probe;dialog.discovered_config=dict(store.config['mcp_servers'][0]);dialog.remote_done({'error':'Authentication required'})
                self.assertEqual(dialog.oauth_challenge_url,'https://example.com/mcp');dialog.discover_oauth();self.assertEqual(created[-1].challenge,dialog.oauth_challenge)
                created[-1].finished.emit({'authorization_server':{'issuer':'https://auth.example/tenant','pkce_s256':True}})
                self.assertIn('https://auth.example/tenant',dialog.status.text());self.assertIn('OAuth sign-in is not yet available',dialog.status.text())
            finally:dialog.close();window.close();app.processEvents();store.db.close()

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
                    self.assertEqual(session.oauth_challenge,{'scope':'private:scope'})
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
        for invalid in ('http://example/mcp','https://user:password@example/mcp','https://example/mcp#fragment','https://example:bad/mcp','https://example.com\\attacker/mcp'):
            with self.subTest(invalid=invalid),self.assertRaises(ValueError):protected_resource_metadata_urls(invalid)
        with self.assertRaises(ValueError):protected_resource_metadata_urls('https://mcp.example/mcp',{'resource_metadata':'http://insecure.example/metadata'})

    def test_authorization_server_metadata_candidates(self):
        self.assertEqual(authorization_server_metadata_urls('https://auth.example/tenant'),['https://auth.example/.well-known/oauth-authorization-server/tenant','https://auth.example/.well-known/openid-configuration/tenant','https://auth.example/tenant/.well-known/openid-configuration'])
        self.assertEqual(authorization_server_metadata_urls('https://auth.example/'),['https://auth.example/.well-known/oauth-authorization-server','https://auth.example/.well-known/openid-configuration'])
        self.assertEqual(authorization_server_metadata_urls('https://auth.example/tenant/')[-1],'https://auth.example/tenant/.well-known/openid-configuration')
        for invalid in ('http://auth.example','https://auth.example/path?x=1','https://auth.example/#fragment','https://a@auth.example/'):
            with self.subTest(invalid=invalid),self.assertRaises(ValueError):authorization_server_metadata_urls(invalid)


if __name__=='__main__':unittest.main()
