import unittest

from agentnik.mcp_oauth import bearer_challenge,protected_resource_metadata_urls,authorization_server_metadata_urls


class MCPOAuthDiscovery(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication
        cls.app=QApplication.instance() or QApplication([])

    def test_dynamic_registration_and_authorization_use_same_loopback_redirect(self):
        import json,threading,time
        from mcp_http_fixture import BaseHTTPRequestHandler,ThreadingHTTPServer
        from urllib.parse import parse_qs,urlencode,urlsplit
        from PySide6.QtCore import QEventLoop,QTimer,QUrl
        from PySide6.QtNetwork import QNetworkAccessManager,QNetworkRequest,QSsl
        from agentnik.mcp_oauth_flow import OAuthAuthorization
        calls=[];browser=[];callbacks=[];callback_manager=QNetworkAccessManager()
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def do_POST(self):
                body=self.rfile.read(int(self.headers['Content-Length']));calls.append((self.path,body,self.headers.get('Authorization'),self.headers.get('Cookie')))
                result={'client_id':'dynamic-client','client_id_expires_at':int(time.time())+3600,'token_endpoint_auth_method':'none','redirect_uris':json.loads(body)['redirect_uris']} if self.path=='/register' else {'access_token':'synthetic-access','refresh_token':'synthetic-refresh','token_type':'Bearer','expires_in':600}
                payload=json.dumps(result).encode();self.send_response(201 if self.path=='/register' else 200);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(payload)));self.end_headers();self.wfile.write(payload)
        server=ThreadingHTTPServer(('127.0.0.1',0),Handler);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start();base='https://127.0.0.1:'+str(server.server_port)
        class LoopbackManager:
            def __init__(self):self.manager=QNetworkAccessManager()
            def post(self,request,data):
                assert request.attribute(QNetworkRequest.Attribute.RedirectPolicyAttribute)==QNetworkRequest.RedirectPolicy.ManualRedirectPolicy
                assert request.sslConfiguration().protocol() in (QSsl.SslProtocol.TlsV1_2,QSsl.SslProtocol.TlsV1_2OrLater,QSsl.SslProtocol.TlsV1_3,QSsl.SslProtocol.TlsV1_3OrLater)
                replacement=QNetworkRequest(request);url=QUrl(request.url());url.setScheme('http');replacement.setUrl(url);return self.manager.post(replacement,data)
        def open_url(value):
            browser.append(value.toString());params=parse_qs(urlsplit(browser[-1]).query)
            QTimer.singleShot(0,lambda:callbacks.append(callback_manager.get(QNetworkRequest(QUrl(params['redirect_uri'][0]+'?'+urlencode({'code':'code','state':params['state'][0]}))))));return True
        metadata={'issuer':base+'/issuer','registration_endpoint':base+'/register','authorization_endpoint':base+'/authorize','token_endpoint':base+'/token','pkce_s256':True};manager=LoopbackManager();job=OAuthAuthorization(base+'/mcp',metadata,'',manager=manager,open_url=open_url,timeout_ms=5000);loop=QEventLoop();out=[];job.finished.connect(lambda value:(out.append(value),loop.quit()));timer=QTimer();timer.setSingleShot(True);timer.timeout.connect(loop.quit);timer.start(7000);job.start()
        try:
            loop.exec();timer.stop();self.assertTrue(out);self.assertEqual(out[0]['client_id'],'dynamic-client');self.assertGreater(out[0]['client_id_expires_at'],int(time.time()));self.assertEqual(out[0]['access_token'],'synthetic-access');self.assertEqual([c[0] for c in calls],['/register','/token'])
            registration=json.loads(calls[0][1]);authorization=parse_qs(urlsplit(browser[0]).query);token=parse_qs(calls[1][1].decode());self.assertEqual(registration['redirect_uris'],authorization['redirect_uri']);self.assertEqual(token['redirect_uri'],authorization['redirect_uri']);self.assertEqual(token['client_id'],['dynamic-client']);self.assertEqual(registration['token_endpoint_auth_method'],'none');self.assertEqual(registration['application_type'],'native');self.assertTrue(all(auth is None and cookie is None for _,_,auth,cookie in calls))
        finally:job.stop();server.shutdown();server.server_close();thread.join(2)

    def test_dynamic_registration_rejects_unsafe_responses_without_opening_browser(self):
        import json,threading
        from mcp_http_fixture import BaseHTTPRequestHandler,ThreadingHTTPServer
        from PySide6.QtCore import QEventLoop,QTimer,QUrl
        from PySide6.QtNetwork import QNetworkAccessManager,QNetworkRequest
        from agentnik.mcp_oauth_flow import OAuthAuthorization
        for mode in ('redirect','secret','redirect-uri','expired','duplicate'):
            with self.subTest(mode=mode):
                calls=[];browser=[]
                class Handler(BaseHTTPRequestHandler):
                    def log_message(self,*args):pass
                    def do_POST(self,mode=mode,calls=calls):
                        request=json.loads(self.rfile.read(int(self.headers['Content-Length'])));calls.append(self.path)
                        if mode=='redirect':self.send_response(302);self.send_header('Location','https://attacker.invalid/register');self.end_headers();return
                        result={'client_id':'dynamic-client','token_endpoint_auth_method':'none','redirect_uris':request['redirect_uris']}
                        if mode=='secret':result['client_secret']='secret'
                        if mode=='redirect-uri':result['redirect_uris']=['http://127.0.0.1:1/other']
                        if mode=='expired':result['client_id_expires_at']=1
                        payload=b'{"client_id":"a","client_id":"b"}' if mode=='duplicate' else json.dumps(result).encode();self.send_response(201);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(payload)));self.end_headers();self.wfile.write(payload)
                server=ThreadingHTTPServer(('127.0.0.1',0),Handler);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start();base='https://127.0.0.1:'+str(server.server_port)
                class LoopbackManager:
                    def __init__(self):self.manager=QNetworkAccessManager()
                    def post(self,request,data):
                        replacement=QNetworkRequest(request);url=QUrl(request.url());url.setScheme('http');replacement.setUrl(url);return self.manager.post(replacement,data)
                metadata={'issuer':base+'/issuer','registration_endpoint':base+'/register','authorization_endpoint':base+'/authorize','token_endpoint':base+'/token','pkce_s256':True};manager=LoopbackManager();job=OAuthAuthorization(base+'/mcp',metadata,'',manager=manager,open_url=lambda value:(browser.append(value),True)[1],timeout_ms=3000);loop=QEventLoop();out=[];job.finished.connect(lambda value:(out.append(value),loop.quit()));timer=QTimer();timer.setSingleShot(True);timer.timeout.connect(loop.quit);timer.start(5000);job.start()
                try:
                    loop.exec();timer.stop();self.assertTrue(out);self.assertIn('error',out[0]);self.assertNotIn('secret',str(out));self.assertEqual(calls,['/register']);self.assertFalse(browser);self.assertFalse(job.listener.isListening())
                finally:job.stop();server.shutdown();server.server_close();thread.join(2)

    def test_cancelling_dynamic_registration_does_not_open_browser_or_retry(self):
        import threading
        from mcp_http_fixture import BaseHTTPRequestHandler,ThreadingHTTPServer
        from PySide6.QtCore import QEventLoop,QTimer,QUrl
        from PySide6.QtNetwork import QNetworkAccessManager,QNetworkRequest
        from agentnik.mcp_oauth_flow import OAuthAuthorization
        started=threading.Event();release=threading.Event();calls=[];browser=[]
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def do_POST(self):
                self.rfile.read(int(self.headers['Content-Length']));calls.append(self.path);started.set();release.wait(4)
                try:self.send_response(201);self.send_header('Content-Type','application/json');self.end_headers();self.wfile.write(b'{"client_id":"unused"}')
                except (BrokenPipeError,ConnectionResetError,ConnectionAbortedError):pass
        server=ThreadingHTTPServer(('127.0.0.1',0),Handler);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start();base='https://127.0.0.1:'+str(server.server_port)
        class LoopbackManager:
            def __init__(self):self.manager=QNetworkAccessManager()
            def post(self,request,data):
                replacement=QNetworkRequest(request);url=QUrl(request.url());url.setScheme('http');replacement.setUrl(url);return self.manager.post(replacement,data)
        metadata={'issuer':base+'/issuer','registration_endpoint':base+'/register','authorization_endpoint':base+'/authorize','token_endpoint':base+'/token','pkce_s256':True};manager=LoopbackManager();job=OAuthAuthorization(base+'/mcp',metadata,'',manager=manager,open_url=lambda value:(browser.append(value),True)[1]);loop=QEventLoop();out=[];job.finished.connect(lambda value:(out.append(value),loop.quit()));poll=QTimer();poll.timeout.connect(lambda:job.stop() if started.is_set() else None);poll.start(10);timeout=QTimer();timeout.setSingleShot(True);timeout.timeout.connect(loop.quit);timeout.start(5000);job.start()
        try:
            loop.exec();poll.stop();timeout.stop();self.assertTrue(out);self.assertIn('cancelled',out[0]['error']);self.assertEqual(calls,['/register']);self.assertFalse(browser);self.assertFalse(job.listener.isListening())
        finally:release.set();job.stop();server.shutdown();server.server_close();thread.join(2)

    def test_settings_oauth_sign_in_saves_keyring_record_and_replaces_old_credential(self):
        import json,tempfile
        from unittest.mock import patch
        from PySide6.QtCore import QObject,Signal
        from PySide6.QtWidgets import QInputDialog
        from agentnik import core
        from agentnik.storage import Store
        from agentnik.ui import Window
        from agentnik.mcp_ui import MCPServers
        jobs=[];credentials={'old-id':'old-bearer'}
        class FakeAuthorization(QObject):
            finished=Signal(object)
            def __init__(self,url,metadata,client_id,scopes,parent,timeout_ms):super().__init__(parent);self.url=url;self.metadata=metadata;self.client_id=client_id;self.scopes=scopes;self.stopped=False;jobs.append(self)
            def start(self):pass
            def stop(self):self.stopped=True;self.finished.emit({'error':'cancelled'})
        def get_password(service,key):return credentials.get(key)
        def set_password(service,key,value):credentials[key]=value
        def delete_password(service,key):credentials.pop(key,None)
        client_id='https://client.example/metadata.json'
        with tempfile.TemporaryDirectory() as folder,patch.object(core,'discover',return_value={}),patch.object(core,'environment_connections',return_value={}),patch('agentnik.mcp_oauth_flow.OAuthAuthorization',FakeAuthorization),patch.object(QInputDialog,'getText',return_value=(client_id,True)) as prompt,patch('keyring.get_password',side_effect=get_password),patch('keyring.set_password',side_effect=set_password),patch('keyring.delete_password',side_effect=delete_password):
            store=Store(folder);server={'name':'Remote','transport':'http','url':'https://mcp.example/mcp','credential_id':'old-id','enabled':True};store.config['mcp_servers']=[server];store.flush();window=Window(store);dialog=MCPServers(window)
            try:
                dialog.list.setCurrentRow(0);dialog.oauth_config=dict(server);dialog.oauth_metadata={'resource':{'scopes_supported':['default']},'authorization_server':{'issuer':'https://auth.example','token_endpoint':'https://auth.example/token','authorization_endpoint':'https://auth.example/authorize','pkce_s256':True,'client_id_metadata_document_supported':True}};dialog.oauth_challenge={'scope':'requested:read'};dialog.oauth_challenge_url=server['url'];dialog.oauth_button.setEnabled(True)
                dialog.sign_in_oauth();self.assertEqual(jobs[-1].scopes,'requested:read');self.assertEqual(jobs[-1].client_id,client_id);self.assertIn('metadata URL',prompt.call_args.args[2]);self.assertTrue(dialog.oauth_button.isEnabled());self.assertEqual(dialog.oauth_button.text(),'Cancel sign-in')
                jobs[-1].finished.emit({'access_token':'access-secret','refresh_token':'refresh-secret','expires_in':600})
                saved=store.config['mcp_servers'][0];self.assertEqual(saved['auth_type'],'oauth');self.assertNotEqual(saved['credential_id'],'old-id');self.assertNotIn('old-id',credentials)
                stored=json.loads(credentials[saved['credential_id']]);self.assertEqual(stored['client_id'],client_id);self.assertEqual(stored['access_token'],'access-secret');self.assertEqual(stored['refresh_token'],'refresh-secret');self.assertEqual(stored['resource_url'],server['url']);self.assertNotIn('access-secret',store.config_path.read_text(encoding='utf-8'));self.assertNotIn('refresh-secret',store.config_path.read_text(encoding='utf-8'));self.assertIn('sign-in saved',dialog.status.text())
            finally:dialog.close();window.close();self.app.processEvents();store.db.close()

    def test_settings_allow_dynamic_registration_without_client_id(self):
        import json,tempfile
        from unittest.mock import patch
        from PySide6.QtCore import QObject,Signal
        from PySide6.QtWidgets import QInputDialog
        from agentnik import core
        from agentnik.storage import Store
        from agentnik.ui import Window
        from agentnik.mcp_ui import MCPServers
        jobs=[];credentials={}
        class FakeAuthorization(QObject):
            finished=Signal(object)
            def __init__(self,url,metadata,client_id,scopes,parent,timeout_ms):super().__init__(parent);self.client_id=client_id;jobs.append(self)
            def start(self):pass
            def stop(self):self.finished.emit({'error':'cancelled'})
        with tempfile.TemporaryDirectory() as folder,patch.object(core,'discover',return_value={}),patch.object(core,'environment_connections',return_value={}),patch('agentnik.mcp_oauth_flow.OAuthAuthorization',FakeAuthorization),patch.object(QInputDialog,'getText',return_value=('',True)),patch('keyring.set_password',side_effect=lambda service,key,value:credentials.__setitem__(key,value)):
            store=Store(folder);server={'name':'Remote','transport':'http','url':'https://mcp.example/mcp','credential_id':'','enabled':True};store.config['mcp_servers']=[server];store.flush();window=Window(store);dialog=MCPServers(window)
            try:
                dialog.list.setCurrentRow(0);dialog.oauth_config=dict(server);dialog.oauth_metadata={'resource':{'scopes_supported':[]},'authorization_server':{'issuer':'https://auth.example','token_endpoint':'https://auth.example/token','authorization_endpoint':'https://auth.example/authorize','registration_endpoint':'https://auth.example/register','pkce_s256':True}};dialog.oauth_button.setEnabled(True)
                dialog.sign_in_oauth();self.assertEqual(jobs[-1].client_id,'');jobs[-1].finished.emit({'client_id':'registered-client','client_id_expires_at':2000000000,'access_token':'synthetic-access','refresh_token':None,'expires_in':600})
                saved=store.config['mcp_servers'][0];stored=json.loads(credentials[saved['credential_id']]);self.assertEqual(saved['auth_type'],'oauth');self.assertEqual(stored['client_id'],'registered-client');self.assertEqual(stored['client_id_expires_at'],2000000000)
            finally:dialog.close();window.close();self.app.processEvents();store.db.close()

    def test_expired_registered_client_id_is_not_reused_for_new_sign_in(self):
        import json,tempfile,time
        from unittest.mock import patch
        from PySide6.QtWidgets import QInputDialog
        from agentnik import core
        from agentnik.storage import Store
        from agentnik.ui import Window
        from agentnik.mcp_ui import MCPServers
        from agentnik.mcp_oauth_credentials import make_record
        with tempfile.TemporaryDirectory() as folder,patch.object(core,'discover',return_value={}),patch.object(core,'environment_connections',return_value={}):
            store=Store(folder);server={'name':'Remote','transport':'http','url':'https://mcp.example/mcp','credential_id':'oauth-id','auth_type':'oauth','enabled':True};store.config['mcp_servers']=[server];store.flush();window=Window(store);dialog=MCPServers(window)
            try:
                dialog.list.setCurrentRow(0);dialog.oauth_config=dict(server);dialog.oauth_metadata={'resource':{'scopes_supported':[]},'authorization_server':{'issuer':'https://auth.example','token_endpoint':'https://auth.example/token','authorization_endpoint':'https://auth.example/authorize','registration_endpoint':'https://auth.example/register','pkce_s256':True}}
                for expiry,expected in ((int(time.time())-1,''),(int(time.time())+3600,'registered-client')):
                    record=make_record(server['url'],'https://auth.example','https://auth.example/token','registered-client',{'access_token':'access','refresh_token':'refresh','expires_in':600},client_id_expires_at=expiry)
                    with patch('keyring.get_password',return_value=json.dumps(record)),patch.object(QInputDialog,'getText',return_value=('',False)) as prompt:
                        dialog.sign_in_oauth();self.assertEqual(prompt.call_args.args[4],expected)
                dialog.oauth_metadata['authorization_server']['issuer']='https://other.example'
                with patch('keyring.get_password',return_value=json.dumps(record)),patch.object(QInputDialog,'getText',return_value=('',False)) as prompt:
                    dialog.sign_in_oauth();self.assertEqual(prompt.call_args.args[4],'')
            finally:dialog.close();window.close();self.app.processEvents();store.db.close()

    def test_settings_oauth_save_failure_and_selection_change_keep_previous_credential(self):
        import tempfile
        from unittest.mock import patch
        from PySide6.QtCore import QObject,Signal
        from PySide6.QtWidgets import QInputDialog
        from agentnik import core
        from agentnik.storage import Store
        from agentnik.ui import Window
        from agentnik.mcp_ui import MCPServers
        jobs=[];credentials={'old-id':'old-bearer'}
        class FakeAuthorization(QObject):
            finished=Signal(object)
            def __init__(self,url,metadata,client_id,scopes,parent,timeout_ms):super().__init__(parent);self.stopped=False;jobs.append(self)
            def start(self):pass
            def stop(self):self.stopped=True;self.finished.emit({'error':'cancelled'})
        def metadata():return {'resource':{'scopes_supported':[]},'authorization_server':{'issuer':'https://auth.example','token_endpoint':'https://auth.example/token','authorization_endpoint':'https://auth.example/authorize','pkce_s256':True}}
        with tempfile.TemporaryDirectory() as folder,patch.object(core,'discover',return_value={}),patch.object(core,'environment_connections',return_value={}),patch('agentnik.mcp_oauth_flow.OAuthAuthorization',FakeAuthorization),patch.object(QInputDialog,'getText',return_value=('public-client',True)),patch('keyring.set_password',side_effect=lambda service,key,value:credentials.__setitem__(key,value)),patch('keyring.delete_password',side_effect=lambda service,key:credentials.pop(key,None)):
            store=Store(folder);server={'name':'Remote','transport':'http','url':'https://mcp.example/mcp','credential_id':'old-id','enabled':True};store.config['mcp_servers']=[server];store.flush();window=Window(store);dialog=MCPServers(window)
            try:
                dialog.list.setCurrentRow(0);dialog.oauth_config=dict(server);dialog.oauth_metadata=metadata();dialog.oauth_button.setEnabled(True);dialog.sign_in_oauth()
                with patch.object(store,'flush',side_effect=OSError('synthetic failure')):jobs[-1].finished.emit({'access_token':'new-secret','refresh_token':'refresh','expires_in':600})
                self.assertEqual(store.config['mcp_servers'][0],server);self.assertEqual(credentials,{'old-id':'old-bearer'});self.assertIn('Could not save',dialog.status.text())
                dialog.oauth_config=dict(server);dialog.oauth_metadata=metadata();dialog.sign_in_oauth()
                def change_config(service,key,value):credentials[key]=value;store.config['mcp_servers']=[dict(server,name='Changed elsewhere')]
                with patch('keyring.set_password',side_effect=change_config):jobs[-1].finished.emit({'access_token':'new-secret','refresh_token':'refresh','expires_in':600})
                self.assertEqual(store.config['mcp_servers'][0]['name'],'Changed elsewhere');self.assertEqual(credentials,{'old-id':'old-bearer'});store.config['mcp_servers']=[server]
                dialog.oauth_config=dict(server);dialog.oauth_metadata=metadata();dialog.sign_in_oauth();dialog.sign_in_oauth();self.assertTrue(jobs[-1].stopped);self.assertIn('cancelled',dialog.status.text());self.assertEqual(credentials,{'old-id':'old-bearer'})
                dialog.oauth_config=dict(server);dialog.oauth_metadata=metadata();dialog.sign_in_oauth();dialog.list.setCurrentRow(-1);self.assertTrue(jobs[-1].stopped);self.assertEqual(credentials,{'old-id':'old-bearer'})
            finally:dialog.close();window.close();self.app.processEvents();store.db.close()

    def test_concurrent_oauth_refresh_is_shared_and_persisted_once(self):
        from unittest.mock import patch
        from PySide6.QtCore import QObject,Signal
        from PySide6.QtWidgets import QApplication
        from agentnik.mcp_oauth_credentials import OAuthCredentialBroker,make_record,read_record,write_record
        app=QApplication.instance() or QApplication([]);jobs=[];values={};out=[]
        class FakeRefresh(QObject):
            finished=Signal(object)
            def __init__(self,record,parent,timeout_ms):super().__init__(parent);self.record=record;self.timeout_ms=timeout_ms;jobs.append(self)
            def start(self):pass
        server={'url':'https://mcp.example/mcp','credential_id':'oauth-id','auth_type':'oauth'}
        old=make_record(server['url'],'https://auth.example','https://auth.example/token','client',{'access_token':'old-secret','refresh_token':'old-refresh','expires_in':1},now=1)
        new=make_record(server['url'],old['issuer'],old['token_endpoint'],old['client_id'],{'access_token':'new-secret','refresh_token':'rotated-secret','expires_in':600})
        with patch('keyring.get_password',side_effect=lambda service,key:values.get(key)),patch('keyring.set_password',side_effect=lambda service,key,value:values.__setitem__(key,value)) as put:
            write_record('oauth-id',old);put.reset_mock();broker=OAuthCredentialBroker(refresh_factory=FakeRefresh)
            broker.request(server,lambda value:out.append(('first',value)),lambda:True);broker.request(server,lambda value:out.append(('second',value)),lambda:True)
            self.assertEqual(len(jobs),1);self.assertEqual(jobs[0].timeout_ms,60000);self.assertTrue(read_record('oauth-id',server['url'])['refresh_pending']);jobs[0].finished.emit({'credential':new});self.assertEqual(put.call_count,2);self.assertEqual(read_record('oauth-id',server['url'])['refresh_token'],'rotated-secret')
            self.assertEqual(out,[('first',{'token':'new-secret'}),('second',{'token':'new-secret'})]);self.assertFalse(broker.pending)
            broker.request(server,lambda value:out.append(('third',value)),lambda:True);self.assertEqual(out[-1],('third',{'token':'new-secret'}));self.assertEqual(len(jobs),1)
            from PySide6.QtCore import QCoreApplication,QEvent
            QCoreApplication.sendPostedEvents(None,QEvent.Type.DeferredDelete)

    def test_refresh_does_not_resurrect_changed_or_removed_server_credential(self):
        from unittest.mock import patch
        from PySide6.QtCore import QObject,Signal
        from PySide6.QtWidgets import QApplication
        from agentnik.mcp_oauth_credentials import OAuthCredentialBroker,make_record,write_record
        app=QApplication.instance() or QApplication([]);jobs=[];values={};out=[];current=[True]
        class FakeRefresh(QObject):
            finished=Signal(object)
            def __init__(self,record,parent,timeout_ms):super().__init__(parent);jobs.append(self)
            def start(self):pass
        server={'url':'https://mcp.example/mcp','credential_id':'oauth-id','auth_type':'oauth'}
        old=make_record(server['url'],'https://auth.example','https://auth.example/token','client',{'access_token':'old','refresh_token':'refresh','expires_in':1},now=1)
        new=make_record(server['url'],old['issuer'],old['token_endpoint'],old['client_id'],{'access_token':'new','refresh_token':'rotated','expires_in':600})
        with patch('keyring.get_password',side_effect=lambda service,key:values.get(key)),patch('keyring.set_password',side_effect=lambda service,key,value:values.__setitem__(key,value)) as put:
            write_record('oauth-id',old);broker=OAuthCredentialBroker(refresh_factory=FakeRefresh);broker.request(server,out.append,lambda:current[0]);put.reset_mock();current[0]=False;values.clear();jobs[0].finished.emit({'credential':new})
            put.assert_not_called();self.assertNotIn('oauth-id',values);self.assertIn('changed',out[0]['error'])
            from PySide6.QtCore import QCoreApplication,QEvent
            QCoreApplication.sendPostedEvents(None,QEvent.Type.DeferredDelete)

    def test_refresh_does_not_overwrite_a_credential_changed_during_request(self):
        from unittest.mock import patch
        from PySide6.QtCore import QObject,Signal,QCoreApplication,QEvent
        from agentnik.mcp_oauth_credentials import OAuthCredentialBroker,make_record,read_record,write_record
        jobs=[];values={};out=[]
        class FakeRefresh(QObject):
            finished=Signal(object)
            def __init__(self,record,parent,timeout_ms):super().__init__(parent);jobs.append(self)
            def start(self):pass
        server={'url':'https://mcp.example/mcp','credential_id':'oauth-id','auth_type':'oauth'}
        def record(access,refresh,now):return make_record(server['url'],'https://auth.example','https://auth.example/token','client',{'access_token':access,'refresh_token':refresh,'expires_in':1},now=now)
        with patch('keyring.get_password',side_effect=lambda service,key:values.get(key)),patch('keyring.set_password',side_effect=lambda service,key,value:values.__setitem__(key,value)) as put:
            write_record('oauth-id',record('old','old-refresh',1));broker=OAuthCredentialBroker(refresh_factory=FakeRefresh);broker.request(server,out.append,lambda:True)
            replacement=record('replacement','new-refresh',1);write_record('oauth-id',replacement);put.reset_mock();jobs[0].finished.emit({'credential':record('stale','stale-refresh',1)})
            put.assert_not_called();self.assertEqual(read_record('oauth-id',server['url']),replacement);self.assertIn('Sign in again',out[0]['error']);QCoreApplication.sendPostedEvents(None,QEvent.Type.DeferredDelete)

    def test_uncertain_refresh_is_not_automatically_repeated(self):
        from unittest.mock import patch
        from PySide6.QtCore import QObject,Signal,QCoreApplication,QEvent
        from agentnik.mcp_oauth_credentials import OAuthCredentialBroker,make_record,read_record,write_record
        jobs=[];values={};out=[]
        class FakeRefresh(QObject):
            finished=Signal(object)
            def __init__(self,record,parent,timeout_ms):super().__init__(parent);jobs.append(self)
            def start(self):pass
        server={'url':'https://mcp.example/mcp','credential_id':'oauth-id','auth_type':'oauth'}
        old=make_record(server['url'],'https://auth.example','https://auth.example/token','client',{'access_token':'old','refresh_token':'refresh','expires_in':1},now=1)
        with patch('keyring.get_password',side_effect=lambda service,key:values.get(key)),patch('keyring.set_password',side_effect=lambda service,key,value:values.__setitem__(key,value)):
            write_record('oauth-id',old);broker=OAuthCredentialBroker(refresh_factory=FakeRefresh);broker.request(server,out.append,lambda:True);jobs[0].finished.emit({'error':'network failure'})
            self.assertTrue(read_record('oauth-id',server['url'])['refresh_pending']);broker.request(server,out.append,lambda:True);self.assertEqual(len(jobs),1);self.assertIn('uncertain',out[-1]['error']);QCoreApplication.sendPostedEvents(None,QEvent.Type.DeferredDelete)

    def test_oauth_bridge_waits_for_credential_and_ignores_late_completion_after_close(self):
        import threading
        from unittest.mock import Mock,patch
        from PySide6.QtWidgets import QApplication
        from agentnik.mcp_code import CodingMCPBridge
        app=QApplication.instance() or QApplication([]);server={'name':'OAuth','transport':'http','url':'https://mcp.example/mcp','credential_id':'oauth-id','auth_type':'oauth','enabled':True};config={'mcp_servers':[server]};callbacks=[]
        class Broker:
            def request(self,selected,callback,is_current):callbacks.append((callback,is_current))
        with patch('agentnik.mcp_oauth_credentials.oauth_credential_broker',return_value=Broker()):
            bridge=CodingMCPBridge(server,config);bridge._start_remote=Mock();request={'action':'discover','payload':{},'done':threading.Event(),'cancelled':threading.Event()};bridge._dispatch(request)
            self.assertEqual(len(callbacks),1);self.assertFalse(request['done'].is_set());callbacks[0][0]({'token':'resolved-token'});bridge._start_remote.assert_called_once_with('resolved-token')
            bridge.pending=None;bridge._start_remote.reset_mock();request2={'action':'discover','payload':{},'done':threading.Event(),'cancelled':threading.Event()};bridge._dispatch(request2);bridge.close();callbacks[1][0]({'token':'late-token'});bridge._start_remote.assert_not_called();self.assertTrue(request2['done'].is_set())

    def test_settings_preserve_oauth_marker_and_use_resolved_access_token(self):
        import tempfile
        from unittest.mock import patch
        from PySide6.QtWidgets import QApplication
        from agentnik import core
        from agentnik.storage import Store
        from agentnik.ui import Window
        from agentnik.mcp_ui import MCPServers
        app=QApplication.instance() or QApplication([])
        class Broker:
            def request(self,server,callback,is_current):
                if is_current():callback({'token':'resolved-access-token'})
        with tempfile.TemporaryDirectory() as folder,patch.object(core,'discover',return_value={}),patch.object(core,'environment_connections',return_value={}),patch('agentnik.mcp_oauth_credentials.oauth_credential_broker',return_value=Broker()):
            store=Store(folder);server={'name':'OAuth','transport':'http','url':'https://mcp.example/mcp','credential_id':'oauth-id','auth_type':'oauth','enabled':True};store.config['mcp_servers']=[server];store.flush();window=Window(store);dialog=MCPServers(window)
            try:
                dialog.list.setCurrentRow(0);dialog.name.setText('Renamed');dialog.save();self.assertEqual(store.config['mcp_servers'][0]['auth_type'],'oauth');self.assertEqual(store.config['mcp_servers'][0]['credential_id'],'oauth-id')
                with patch('agentnik.mcp_remote.RemoteProbe') as probe:
                    dialog.test();self.assertEqual(probe.call_args.args[1],'resolved-access-token');probe.return_value.start.assert_called_once();dialog.remote=None
                item=dict(store.config['mcp_servers'][0]);tool={'name':'work','schema_status':'available','schema':{'type':'object'},'description_clipped':False};dialog.discovered={'config':item,'tools':[tool],'task_capabilities':{}};dialog.tool_choice.addItem('work');dialog.tool_args.setPlainText('{}')
                with patch('agentnik.mcp_remote.RemoteProbe') as probe:
                    dialog.validated_call(True,0,item,tool,{},'{}');self.assertEqual(probe.call_args.args[1],'resolved-access-token');dialog.remote=None
                    probe.reset_mock();dialog.tool_args.setPlainText('{"value":"resolved-access-token"}');dialog.validated_call(True,0,item,tool,{'value':'resolved-access-token'},dialog.tool_args.toPlainText());probe.assert_not_called();self.assertIn('credential',dialog.status.text())
                with patch('keyring.set_password'),patch('keyring.delete_password'):
                    dialog.token.setText('manual-bearer');dialog.save();self.assertNotIn('auth_type',store.config['mcp_servers'][0])
            finally:dialog.close();window.close();app.processEvents();store.db.close()

    def test_oauth_keyring_records_bind_server_and_preserve_bearer_storage(self):
        from agentnik.mcp_oauth_credentials import make_record,read_record,write_record,credential_state
        class Backend:
            def __init__(self):self.values={}
            def set_password(self,service,name,value):self.values[(service,name)]=value
            def get_password(self,service,name):return self.values.get((service,name))
        backend=Backend();backend.set_password('Agentnik','legacy','legacy-token')
        record=make_record('https://mcp.example/mcp','https://auth.example','https://auth.example/token','client',{'access_token':'access-secret','refresh_token':'refresh-secret','expires_in':100},now=1000)
        write_record('oauth-id',record,backend);self.assertEqual(read_record('oauth-id','https://mcp.example/mcp',backend),record)
        self.assertEqual(backend.get_password('Agentnik','legacy'),'legacy-token')
        with self.assertRaises(ValueError):read_record('oauth-id','https://other.example/mcp',backend)
        with self.assertRaises(ValueError):read_record('legacy','https://mcp.example/mcp',backend)
        self.assertEqual(credential_state(record,now=1000),'ready');self.assertEqual(credential_state(record,now=1071),'refresh')
        no_refresh=dict(record,refresh_token=None);self.assertEqual(credential_state(no_refresh,now=1099),'ready');self.assertEqual(credential_state(no_refresh,now=1100),'expired')
        expired_client=dict(record,client_id_expires_at=1050);self.assertEqual(credential_state(expired_client,now=1071),'ready');self.assertEqual(credential_state(expired_client,now=1100),'expired')
        replacement=make_record(record['resource_url'],record['issuer'],record['token_endpoint'],record['client_id'],{'access_token':'new','refresh_token':None,'expires_in':200},now=1100,previous_refresh=record['refresh_token'])
        self.assertEqual(replacement['refresh_token'],'refresh-secret');self.assertEqual(replacement['expires_at'],1300)

    def test_oauth_refresh_rotates_token_once_without_credential_leak(self):
        import json,threading
        from mcp_http_fixture import BaseHTTPRequestHandler,ThreadingHTTPServer
        from urllib.parse import parse_qs
        from PySide6.QtCore import QEventLoop,QTimer,QUrl
        from PySide6.QtNetwork import QNetworkAccessManager,QNetworkRequest,QSsl
        from PySide6.QtWidgets import QApplication
        from agentnik.mcp_oauth_credentials import make_record,OAuthRefresh
        app=QApplication.instance() or QApplication([])
        for mode in ('success','redirect','invalid'):
            with self.subTest(mode=mode):
                calls=[]
                class Handler(BaseHTTPRequestHandler):
                    def log_message(self,*args):pass
                    def do_POST(self,mode=mode,calls=calls):
                        body=self.rfile.read(int(self.headers['Content-Length']));calls.append((self.path,parse_qs(body.decode()),self.headers.get('Authorization'),self.headers.get('Cookie')))
                        if mode=='redirect':self.send_response(302);self.send_header('Location','https://attacker.invalid/token');self.end_headers();return
                        payload=json.dumps({'access_token':'new-secret','refresh_token':'rotated-secret','token_type':'Bearer' if mode=='success' else 'Basic','expires_in':600}).encode();self.send_response(200);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(payload)));self.end_headers();self.wfile.write(payload)
                server=ThreadingHTTPServer(('127.0.0.1',0),Handler);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start();base='https://127.0.0.1:'+str(server.server_port)
                class LoopbackManager:
                    def __init__(self):self.manager=QNetworkAccessManager()
                    def post(self,request,data):
                        assert request.attribute(QNetworkRequest.Attribute.RedirectPolicyAttribute)==QNetworkRequest.RedirectPolicy.ManualRedirectPolicy
                        assert request.sslConfiguration().protocol() in (QSsl.SslProtocol.TlsV1_2,QSsl.SslProtocol.TlsV1_2OrLater,QSsl.SslProtocol.TlsV1_3,QSsl.SslProtocol.TlsV1_3OrLater)
                        replacement=QNetworkRequest(request);url=QUrl(request.url());url.setScheme('http');replacement.setUrl(url);return self.manager.post(replacement,data)
                record=make_record(base+'/mcp',base+'/issuer',base+'/token','client',{'access_token':'old-secret','refresh_token':'refresh-secret','expires_in':60});manager=LoopbackManager();job=OAuthRefresh(record,manager=manager);loop=QEventLoop();out=[];job.finished.connect(lambda value:(out.append(value),loop.quit()));timer=QTimer();timer.setSingleShot(True);timer.timeout.connect(loop.quit);timer.start(5000);job.start()
                try:
                    loop.exec();timer.stop();self.assertTrue(out);self.assertEqual(len(calls),1);self.assertEqual(calls[0][1]['refresh_token'],['refresh-secret']);self.assertEqual(calls[0][1]['resource'],[base+'/mcp']);self.assertIsNone(calls[0][2]);self.assertIsNone(calls[0][3]);self.assertIsNone(job.record)
                    if mode=='success':self.assertEqual(out[0]['credential']['access_token'],'new-secret');self.assertEqual(out[0]['credential']['refresh_token'],'rotated-secret')
                    else:self.assertIn('error',out[0]);self.assertNotIn('secret',str(out))
                finally:job.stop();server.shutdown();server.server_close();thread.join(2)

    def test_authorization_pkce_state_and_token_exchange(self):
        import base64,hashlib,json,threading
        from mcp_http_fixture import BaseHTTPRequestHandler,ThreadingHTTPServer
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
            QTimer.singleShot(100,lambda:send({'code':'synthetic-code','state':state}))
            QTimer.singleShot(150,lambda:send({'code':'synthetic-code','state':state,'iss':'https://wrong.example'}))
            QTimer.singleShot(200,lambda:send({'code':'synthetic-code','state':state,'iss':base+'/issuer'}))
            return True
        metadata={'issuer':base+'/issuer','authorization_endpoint':base+'/authorize?existing=value','token_endpoint':base+'/token','pkce_s256':True,'authorization_response_iss_parameter_supported':True}
        client_id='https://client.example/metadata.json'
        manager=LoopbackManager();job=OAuthAuthorization(base+'/mcp?tools=selected',metadata,client_id,'read write',manager=manager,open_url=open_url,timeout_ms=5000);loop=QEventLoop();out=[];job.finished.connect(lambda value:(out.append(value),loop.quit()));timer=QTimer();timer.setSingleShot(True);timer.timeout.connect(loop.quit);timer.start(7000);job.start()
        try:
            loop.exec();timer.stop();self.assertEqual(out,[{'access_token':'synthetic-access','refresh_token':'synthetic-refresh','expires_in':600}]);self.assertEqual(len(received),1)
            sent=received[0][1];auth=parse_qs(urlsplit(browsed[0]).query)
            self.assertEqual(sent['code'],['synthetic-code']);self.assertEqual(sent['client_id'],[client_id]);self.assertEqual(auth['client_id'],[client_id]);self.assertEqual(sent['resource'],[base+'/mcp?tools=selected']);self.assertEqual(auth['resource'],sent['resource']);self.assertEqual(auth['scope'],['read write']);self.assertEqual(auth['code_challenge_method'],['S256'])
            expected=base64.urlsafe_b64encode(hashlib.sha256(sent['code_verifier'][0].encode()).digest()).rstrip(b'=').decode();self.assertEqual(auth['code_challenge'],[expected]);self.assertIsNone(received[0][2]);self.assertIsNone(received[0][3]);self.assertEqual(len(replies),5)
            self.assertEqual([reply.attribute(QNetworkRequest.Attribute.HttpStatusCodeAttribute) for reply in replies],[400,400,400,400,200])
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
        from mcp_http_fixture import BaseHTTPRequestHandler,ThreadingHTTPServer
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
        self.assertFalse(parse_authorization_metadata(meta,issuer)['authorization_response_iss_parameter_supported'])
        self.assertTrue(parse_authorization_metadata(dict(meta,authorization_response_iss_parameter_supported=True),issuer)['authorization_response_iss_parameter_supported'])
        with self.assertRaises(ValueError):parse_authorization_metadata(dict(meta,authorization_response_iss_parameter_supported='true'),issuer)
        self.assertFalse(parse_authorization_metadata(meta,issuer)['client_id_metadata_document_supported'])
        self.assertTrue(parse_authorization_metadata(dict(meta,client_id_metadata_document_supported=True),issuer)['client_id_metadata_document_supported'])
        with self.assertRaises(ValueError):parse_authorization_metadata(dict(meta,client_id_metadata_document_supported='true'),issuer)
        with self.assertRaises(ValueError):parse_authorization_metadata(dict(meta,issuer='https://attacker.example'),issuer)
        with self.assertRaises(ValueError):parse_authorization_metadata(dict(meta,token_endpoint='http://insecure.example'),issuer)
        self.assertFalse(parse_authorization_metadata(dict(meta,code_challenge_methods_supported=[]),issuer)['pkce_s256'])
        self.assertFalse(parse_authorization_metadata(dict(meta,token_endpoint_auth_methods_supported=['client_secret_basic']),issuer)['public_client_supported'])
        self.assertTrue(parse_authorization_metadata(dict(meta,token_endpoint_auth_methods_supported=['none']),issuer)['public_client_supported'])
        self.assertTrue(parse_authorization_metadata(dict(meta,grant_types_supported=['authorization_code','refresh_token']),issuer)['refresh_grant_supported'])
        with self.assertRaises(ValueError):parse_authorization_metadata(dict(meta,grant_types_supported='refresh_token'),issuer)

    def test_async_metadata_discovery_fallback_and_no_credentials(self):
        import json,threading
        from mcp_http_fixture import BaseHTTPRequestHandler,ThreadingHTTPServer
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
        from mcp_http_fixture import BaseHTTPRequestHandler,ThreadingHTTPServer
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
                self.assertIn('https://auth.example/tenant',dialog.status.text());self.assertTrue(dialog.oauth_button.isEnabled())
                dialog.discover_oauth();created[-1].finished.emit({'authorization_server':{'issuer':'https://auth.example/tenant','pkce_s256':True,'public_client_supported':False}})
                self.assertFalse(dialog.oauth_button.isEnabled());self.assertIn('does not support public clients',dialog.status.text())
            finally:dialog.close();window.close();app.processEvents();store.db.close()

    def test_remote_authentication_failures_are_actionable_and_do_not_echo_server_text(self):
        import json,threading
        from mcp_http_fixture import BaseHTTPRequestHandler,ThreadingHTTPServer
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
                session=RemoteSession('http://127.0.0.1:'+str(server.server_port)+'/mcp','',timeout_seconds=3,prefer_modern=False);loop=QEventLoop();out=[];network=[]
                from PySide6.QtNetwork import QNetworkRequest
                session.manager.finished.connect(lambda reply:network.append((session.phase,reply.attribute(QNetworkRequest.Attribute.HttpStatusCodeAttribute),str(reply.error()),reply.errorString())))
                session.discovered.connect(lambda info:session.call(info['tool_details'][0],{}));session.ended.connect(lambda error:(out.append(error),loop.quit()));session.start();timer=QTimer();timer.setSingleShot(True);timer.timeout.connect(loop.quit);timer.start(5000)
                try:
                    loop.exec();timer.stop();self.assertTrue(out);self.assertIn('sign in',out[0]['error'].lower(),f'calls={calls!r}; network={network!r}');self.assertNotIn('private:scope',out[0]['error'])
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
        for invalid in ('http://example/mcp','https://user:password@example/mcp','https://example/mcp#fragment','https://example:bad/mcp','https://example.com\\attacker/mcp','https://example.com/<img>/mcp'):
            with self.subTest(invalid=invalid),self.assertRaises(ValueError):protected_resource_metadata_urls(invalid)
        with self.assertRaises(ValueError):protected_resource_metadata_urls('https://mcp.example/mcp',{'resource_metadata':'http://insecure.example/metadata'})

    def test_authorization_server_metadata_candidates(self):
        self.assertEqual(authorization_server_metadata_urls('https://auth.example/tenant'),['https://auth.example/.well-known/oauth-authorization-server/tenant','https://auth.example/.well-known/openid-configuration/tenant','https://auth.example/tenant/.well-known/openid-configuration'])
        self.assertEqual(authorization_server_metadata_urls('https://auth.example/'),['https://auth.example/.well-known/oauth-authorization-server','https://auth.example/.well-known/openid-configuration'])
        self.assertEqual(authorization_server_metadata_urls('https://auth.example/tenant/')[-1],'https://auth.example/tenant/.well-known/openid-configuration')
        for invalid in ('http://auth.example','https://auth.example/path?x=1','https://auth.example/#fragment','https://a@auth.example/'):
            with self.subTest(invalid=invalid),self.assertRaises(ValueError):authorization_server_metadata_urls(invalid)


if __name__=='__main__':unittest.main()
