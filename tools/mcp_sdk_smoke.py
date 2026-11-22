"""Optional offline interoperability smoke test against the installed MCP Python SDK.

Run explicitly with an environment containing MCP Python SDK 2.x and PySide6.
The test starts its own server and uses only synthetic, in-memory data.
"""
import json
import sys
from importlib.metadata import version
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))


def make_server(cancelled=None,resumption=None):
    from mcp.server.mcpserver import MCPServer,Context
    from typing import TypedDict
    class Addition(TypedDict):
        sum:int
    server=MCPServer('Agentnik smoke',version='1')

    @server.tool(structured_output=True)
    def add(a:int,b:int)->Addition:
        """Add two synthetic integers."""
        return {'sum':a+b}

    @server.tool()
    async def ping_client(ctx:Context)->str:
        """Ping the client before returning a synthetic result."""
        await ctx.session.send_ping()
        return 'Ping acknowledged'

    @server.tool()
    async def ping_scoped_client(ctx:Context)->str:
        """Ping the client on the current request stream."""
        from mcp.types import PingRequest,EmptyResult
        from mcp.shared.message import ServerMessageMetadata
        await ctx.session.send_request(PingRequest(),EmptyResult,metadata=ServerMessageMetadata(related_request_id=ctx.request_id))
        return 'Ping acknowledged'

    @server.resource('smoke://fixture')
    def fixture()->str:
        return 'Synthetic resource'

    @server.resource('smoke://items/{item}')
    def item_resource(item:str)->str:
        return 'Synthetic item '+item

    @server.prompt()
    def greet(name:str)->str:
        return 'Hello '+name

    if cancelled is not None:
        import asyncio
        @server.tool()
        async def wait_for_cancel(ctx:Context)->str:
            """Wait until the test cancels this synthetic operation."""
            try:
                await ctx.report_progress(1,2,'Waiting for cancellation')
                await asyncio.sleep(30)
                return 'Unexpected completion'
            finally:cancelled.set()

    if resumption is not None:
        import asyncio
        @server.tool()
        async def reconnect_tool(ctx:Context)->str:
            """Close the response stream before finishing this synthetic call."""
            resumption['calls']+=1
            await asyncio.sleep(.2)
            await ctx.close_sse_stream()
            await asyncio.sleep(.2)
            return 'Resumed result'

        @server.tool()
        async def reconnect_standalone(ctx:Context)->str:
            """Close the notification stream and send a notification during the gap."""
            async def wait_event(event):
                for _ in range(200):
                    if event.is_set():return True
                    await asyncio.sleep(.02)
                return False
            resumption['calls']+=1
            if not await wait_event(resumption['initial_get']):raise RuntimeError('Standalone stream did not open')
            await asyncio.sleep(.1)
            await ctx.session.send_resource_list_changed()
            if not await wait_event(resumption['first_notice']):raise RuntimeError('First notification was not received')
            await ctx.close_standalone_sse_stream()
            if not await wait_event(resumption['disconnected']):raise RuntimeError('Standalone disconnect was not observed')
            await ctx.session.send_resource_list_changed()
            return 'Standalone stream closed'

    return server


def run(session,transport):
    from PySide6.QtCore import QCoreApplication,QEventLoop,QTimer
    from agentnik.mcp_schema import validate_tool_arguments,validate_tool_result
    app=QCoreApplication.instance() or QCoreApplication([])
    loop=QEventLoop();result={'step':'discover'};timer=QTimer();timer.setSingleShot(True)

    def fail(message):
        result['error']=str(message);loop.quit()

    def discovered(info):
        try:
            tool=next(item for item in info['tool_details'] if item['name']=='add')
            result['ping_tool']=next(item for item in info['tool_details'] if item['name']=='ping_client')
            result['ping_scoped_tool']=next(item for item in info['tool_details'] if item['name']=='ping_scoped_client')
            if tool.get('output_schema_status')!='available':raise RuntimeError('Output schema was not discovered')
            validate_tool_arguments(tool['schema'],{'a':2,'b':3});result['tool']=tool
            result['protocol']=info['protocol'];result['step']='call'
            if not session.call(tool,{'a':2,'b':3}):raise RuntimeError('Tool call was rejected')
        except Exception as exc:fail(exc)

    def called(message):
        try:
            if 'error' in message:raise RuntimeError(message['error'])
            output=message['call_result']
            if result['step']=='call':
                validate_tool_result(result['tool'],output)
                if output.get('structuredContent',{}).get('sum')!=5:raise RuntimeError('Unexpected synthetic tool result: '+json.dumps(output))
                result['step']='ping'
                if not session.call(result['ping_tool'],{}):raise RuntimeError('Ping tool call was rejected')
                return
            if not any(block.get('text')=='Ping acknowledged' for block in output['content']):raise RuntimeError('SDK server ping was not acknowledged')
            if result['step']=='ping':
                result['step']='ping_scoped'
                if not session.call(result['ping_scoped_tool'],{}):raise RuntimeError('Request-scoped ping tool was rejected')
                return
            result['step']='resources'
            if not session.list_resources():raise RuntimeError('Resource listing was rejected')
        except Exception as exc:fail(exc)

    def resources(message):
        try:
            if 'error' in message:raise RuntimeError(message['error'])
            if result['step']=='resources':
                uri=next(item['uri'] for item in message['resources'] if item['uri']=='smoke://fixture')
                result['step']='read'
                if not session.read_resource(uri):raise RuntimeError('Resource read was rejected')
            elif result['step']=='read':
                if message['contents'][0]['text']!='Synthetic resource':raise RuntimeError('Unexpected resource contents')
                result['step']='templates'
                if not session.list_resource_templates():raise RuntimeError('Template listing was rejected')
            elif result['step']=='templates':
                template=next(item for item in message['templates'] if item['uriTemplate']=='smoke://items/{item}')
                result['step']='template_read'
                if not session.read_resource_template(template,{'item':'alpha'},'smoke://items/alpha'):raise RuntimeError('Template read was rejected')
            else:
                if message['contents'][0]['text']!='Synthetic item alpha':raise RuntimeError('Unexpected template contents')
                result['step']='prompts'
                if not session.list_prompts():raise RuntimeError('Prompt listing was rejected')
        except Exception as exc:fail(exc)

    def prompts(message):
        try:
            if 'error' in message:raise RuntimeError(message['error'])
            if result['step']=='prompts':
                prompt=next(item for item in message['prompts'] if item['name']=='greet');result['step']='prompt_get'
                if not session.list_prompts({'prompt':prompt,'arguments':{'name':'world'}}):raise RuntimeError('Prompt retrieval was rejected')
            else:
                if message['messages'][0]['content']['text']!='Hello world':raise RuntimeError('Unexpected prompt content')
                result['step']='complete';loop.quit()
        except Exception as exc:fail(exc)

    session.discovered.connect(discovered);session.called.connect(called);session.resources.connect(resources);session.prompts.connect(prompts)
    session.ended.connect(lambda message:fail(message.get('error','Server exited')) if result['step']!='complete' else None)
    timer.timeout.connect(lambda:fail('Smoke test timed out'));timer.start(30000);session.start();loop.exec();timer.stop()
    if transport=='stdio':session.close()
    else:
        if not session.closed:
            cleanup=QEventLoop();closed=[];session.finished.connect(lambda message:(closed.append(message),cleanup.quit()));QTimer.singleShot(4000,cleanup.quit);session.shutdown();cleanup.exec()
            if not closed or closed[0].get('session_closed') is not True:fail('HTTPS session shutdown was not confirmed')
        session.manager.clearConnectionCache();app.processEvents()
    if result.get('error'):raise RuntimeError(result['step']+': '+result['error'])
    return {'sdk_version':version('mcp'),'transport':transport,'protocol':result['protocol'],'checks':['discovery','tool call and output schema','server ping','request-scoped server ping','resource list/read','template list/read','prompt list/get']}


def run_https(test_cancel=False,test_resume=False,test_standalone_resume=False,test_oauth=False,test_oauth_flow=False,test_oauth_refresh=False,test_oauth_ui=False):
    import datetime
    import ipaddress
    import socket
    import ssl
    import tempfile
    import threading
    import time
    import uvicorn
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes,serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID
    from PySide6.QtCore import QCoreApplication
    from PySide6.QtNetwork import QSslCertificate,QSslConfiguration
    from agentnik.mcp_remote import RemoteSession
    from agentnik import tls

    if test_oauth_ui:
        from PySide6.QtWidgets import QApplication
        app=QApplication.instance() or QApplication([])
    else:app=QCoreApplication.instance() or QCoreApplication([])
    key=rsa.generate_private_key(public_exponent=65537,key_size=2048)
    name=x509.Name([x509.NameAttribute(NameOID.COMMON_NAME,'Agentnik local smoke')])
    now=datetime.datetime.now(datetime.timezone.utc)
    cert=(x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key()).serial_number(x509.random_serial_number()).not_valid_before(now-datetime.timedelta(minutes=1)).not_valid_after(now+datetime.timedelta(hours=1)).add_extension(x509.BasicConstraints(ca=True,path_length=None),critical=True).add_extension(x509.SubjectAlternativeName([x509.IPAddress(ipaddress.ip_address('127.0.0.1'))]),critical=False).sign(key,hashes.SHA256()))
    with tempfile.TemporaryDirectory(prefix='agentnik-mcp-sdk-') as folder:
        cert_path=Path(folder)/'cert.pem';key_path=Path(folder)/'key.pem'
        cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
        key_path.write_bytes(key.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,serialization.NoEncryption()))
        config=QSslConfiguration.defaultConfiguration();original=QSslConfiguration(config)
        config.setCaCertificates(config.caCertificates()+QSslCertificate.fromData(cert_path.read_bytes()));QSslConfiguration.setDefaultConfiguration(config)
        listener=socket.socket();listener.bind(('127.0.0.1',0));listener.listen(64);port=listener.getsockname()[1]
        def ssl_context(_config,factory):
            context=factory();context.minimum_version=ssl.TLSVersion.TLSv1_2;return context
        cancelled=threading.Event();observed=[];oauth_requests=[];resume={'calls':0,'gets':[],'initial_get':threading.Event(),'first_notice':threading.Event(),'disconnected':threading.Event(),'stored_before_reconnect':False};resumption_test=test_resume or test_standalone_resume
        event_store=None
        if resumption_test:
            from mcp.server.streamable_http import EventStore,EventMessage
            class MemoryEventStore(EventStore):
                def __init__(self):self.events=[]
                async def store_event(self,stream_id,message):
                    if test_standalone_resume and getattr(message,'method',None)=='notifications/resources/list_changed' and resume['disconnected'].is_set() and not any(resume['gets']):resume['stored_before_reconnect']=True
                    event_id=str(len(self.events)+1);self.events.append((event_id,stream_id,message));return event_id
                async def replay_events_after(self,last_event_id,send_callback):
                    position=next((i for i,event in enumerate(self.events) if event[0]==last_event_id),None)
                    if position is None:return None
                    stream_id=self.events[position][1]
                    for event_id,event_stream,message in self.events[position+1:]:
                        if event_stream==stream_id and message is not None:await send_callback(EventMessage(message,event_id))
                    return stream_id
            event_store=MemoryEventStore()
        sdk_app=make_server(cancelled if test_cancel else None,resume if resumption_test else None).streamable_http_app(event_store=event_store,retry_interval=100 if resumption_test else None)
        async def monitored_app(scope,receive,send):
            chunks=[]
            if (test_oauth_flow or test_oauth_refresh or test_oauth_ui) and scope['type']=='http' and scope['method']=='POST' and scope['path']=='/token':
                from starlette.responses import JSONResponse
                body=await receive();oauth_requests.append(body.get('body',b''))
                response={'access_token':'synthetic-access','token_type':'Bearer','expires_in':600}
                if test_oauth_refresh:response['refresh_token']='synthetic-rotated'
                await JSONResponse(response)(scope,receive,send);return
            if (test_oauth or test_oauth_ui) and scope['type']=='http' and scope['method']=='GET':
                from starlette.responses import JSONResponse
                base='https://127.0.0.1:'+str(port)
                if scope['path']=='/.well-known/oauth-protected-resource/mcp':
                    await JSONResponse({'resource':base+'/mcp','authorization_servers':[base+'/tenant']})(scope,receive,send);return
                if scope['path']=='/.well-known/oauth-authorization-server/tenant':
                    await JSONResponse({'issuer':base+'/tenant','authorization_endpoint':base+'/authorize','token_endpoint':base+'/token','code_challenge_methods_supported':['S256']})(scope,receive,send);return
            if test_oauth_ui and scope['type']=='http' and scope['path']=='/mcp' and dict(scope['headers']).get(b'authorization')!=b'Bearer synthetic-access':
                from starlette.responses import Response
                await Response(status_code=401,headers={'WWW-Authenticate':'Bearer'})(scope,receive,send);return
            if resumption_test and scope['type']=='http' and scope['method']=='GET':
                resume['gets'].append(dict(scope['headers']).get(b'last-event-id'))
            async def monitored_send(item):
                await send(item)
                if test_standalone_resume and scope['type']=='http' and scope['method']=='GET' and not dict(scope['headers']).get(b'last-event-id') and item['type']=='http.response.start' and item['status']==200:resume['initial_get'].set()
            async def monitored_receive():
                item=await receive()
                if scope['type']=='http' and item['type']=='http.request':
                    chunks.append(item.get('body',b''))
                    if not item.get('more_body',False):
                        try:
                            payload=json.loads(b''.join(chunks))
                            if payload.get('method') in ('tools/call','notifications/cancelled'):observed.append(payload)
                        except (ValueError,AttributeError):pass
                return item
            await sdk_app(scope,monitored_receive,monitored_send)
        settings=uvicorn.Config(monitored_app,host='127.0.0.1',port=port,ssl_certfile=str(cert_path),ssl_keyfile=str(key_path),ssl_context_factory=ssl_context,log_level='error',timeout_graceful_shutdown=2)
        server=uvicorn.Server(settings);thread=threading.Thread(target=lambda:server.run(sockets=[listener]),daemon=True);thread.start()
        try:
            deadline=time.monotonic()+15
            while not server.started and thread.is_alive() and time.monotonic()<deadline:time.sleep(.05)
            if not server.started:raise RuntimeError('Local HTTPS server did not start')
            if tls.relaxed():raise RuntimeError('TLS verification must remain enabled')
            context=ssl.create_default_context(cafile=str(cert_path));context.minimum_version=ssl.TLSVersion.TLSv1_2
            with socket.create_connection(('127.0.0.1',port),timeout=5) as connection:
                with context.wrap_socket(connection,server_hostname='127.0.0.1') as secure:
                    negotiated=secure.version()
                    if negotiated not in ('TLSv1.2','TLSv1.3'):raise RuntimeError('Unexpected TLS protocol')
            url='https://127.0.0.1:'+str(port)+'/mcp'
            if test_oauth:result=run_oauth_discovery(url)
            elif test_oauth_flow:result=run_oauth_flow(url,oauth_requests)
            elif test_oauth_refresh:result=run_oauth_refresh(url,oauth_requests)
            elif test_oauth_ui:result=run_oauth_ui(url,oauth_requests)
            else:
                session=RemoteSession(url,'',timeout_seconds=15)
                result=run_cancel(session,cancelled,observed) if test_cancel else run_standalone_resume(session,resume) if test_standalone_resume else run_resume(session,resume) if test_resume else run(session,'https')
            result['tls_probe_version']=negotiated
        finally:
            server.should_exit=True;thread.join(10);listener.close();QSslConfiguration.setDefaultConfiguration(original)
            if thread.is_alive():raise RuntimeError('Local HTTPS server did not stop')
    return result


def run_oauth_ui(url,requests):
    import tempfile
    from unittest.mock import patch
    from urllib.parse import parse_qs,urlencode,urlsplit
    from PySide6.QtCore import QEventLoop,QTimer,QUrl
    from PySide6.QtGui import QDesktopServices
    from PySide6.QtNetwork import QNetworkAccessManager,QNetworkRequest
    from PySide6.QtWidgets import QApplication,QInputDialog
    from agentnik import core
    from agentnik.storage import Store
    from agentnik.ui import Window
    from agentnik.mcp_ui import MCPServers
    app=QApplication.instance();callback_manager=QNetworkAccessManager();callbacks=[];browser=[];credentials={}
    def open_url(value):
        browser.append(value.toString());params=parse_qs(urlsplit(browser[-1]).query)
        QTimer.singleShot(0,lambda:callbacks.append(callback_manager.get(QNetworkRequest(QUrl(params['redirect_uri'][0]+'?'+urlencode({'code':'synthetic-code','state':params['state'][0]}))))))
        return True
    def wait_until(predicate):
        loop=QEventLoop();poll=QTimer();poll.timeout.connect(lambda:loop.quit() if predicate() else None);poll.start(10);deadline=QTimer();deadline.setSingleShot(True);deadline.timeout.connect(loop.quit);deadline.start(10000);loop.exec();poll.stop();deadline.stop()
        if not predicate():raise RuntimeError('OAuth UI smoke test timed out')
    with tempfile.TemporaryDirectory(prefix='agentnik-oauth-ui-') as folder,patch.object(core,'discover',return_value={}),patch.object(core,'environment_connections',return_value={}),patch.object(QDesktopServices,'openUrl',side_effect=open_url),patch.object(QInputDialog,'getText',return_value=('synthetic-client',True)),patch('keyring.get_password',side_effect=lambda service,key:credentials.get(key)),patch('keyring.set_password',side_effect=lambda service,key,value:credentials.__setitem__(key,value)),patch('keyring.delete_password',side_effect=lambda service,key:credentials.pop(key,None)):
        store=Store(folder);store.config['mcp_servers']=[{'name':'Synthetic','transport':'http','url':url,'credential_id':'','enabled':True}];store.flush();window=Window(store);dialog=MCPServers(window)
        try:
            dialog.list.setCurrentRow(0);dialog.discover_oauth();wait_until(lambda:dialog.oauth_discovery is None)
            if not dialog.oauth_metadata or not dialog.oauth_button.isEnabled():raise RuntimeError('OAuth metadata discovery did not enable sign-in')
            dialog.sign_in_oauth();wait_until(lambda:dialog.oauth_authorization is None)
            saved=store.config['mcp_servers'][0]
            if saved.get('auth_type')!='oauth' or saved.get('credential_id') not in credentials or 'synthetic-access' in json.dumps(store.config):raise RuntimeError('OAuth credential was not stored securely')
            dialog.test();wait_until(lambda:dialog.remote is None)
            if not dialog.discovered or not browser or len(requests)!=1:raise RuntimeError('OAuth-backed MCP connection failed')
            result={'sdk_version':version('mcp'),'transport':'https','checks':['settings discovery','browser callback','keyring credential','OAuth-backed MCP discovery']}
        finally:dialog.close();window.close();app.processEvents();store.db.close();callback_manager.clearConnectionCache()
    return result


def run_oauth_refresh(url,requests):
    from urllib.parse import parse_qs
    from PySide6.QtCore import QEventLoop,QTimer
    from agentnik.mcp_oauth_credentials import make_record,OAuthRefresh
    base=url.rsplit('/mcp',1)[0];record=make_record(url,base+'/issuer',base+'/token','synthetic-client',{'access_token':'synthetic-old','refresh_token':'synthetic-refresh','expires_in':1},now=1)
    job=OAuthRefresh(record,timeout_ms=10000);loop=QEventLoop();out=[];job.finished.connect(lambda value:(out.append(value),loop.quit()));timer=QTimer();timer.setSingleShot(True);timer.timeout.connect(loop.quit);timer.start(12000);job.start();loop.exec();timer.stop()
    if not out or 'credential' not in out[0] or len(requests)!=1:raise RuntimeError('OAuth refresh failed')
    body=parse_qs(requests[0].decode());updated=out[0]['credential']
    if body.get('resource')!=[url] or body.get('grant_type')!=['refresh_token'] or body.get('refresh_token')!=['synthetic-refresh'] or updated['refresh_token']!='synthetic-rotated':raise RuntimeError('OAuth refresh rotation or resource binding failed')
    job.manager.clearConnectionCache()
    return {'sdk_version':version('mcp'),'transport':'https','checks':['verified HTTPS refresh','resource binding','refresh token rotation']}


def run_oauth_flow(url,requests):
    import base64,hashlib
    from urllib.parse import parse_qs,urlencode,urlsplit
    from PySide6.QtCore import QEventLoop,QTimer,QUrl
    from PySide6.QtNetwork import QNetworkAccessManager,QNetworkRequest
    from agentnik.mcp_oauth_flow import OAuthAuthorization
    base=url.rsplit('/mcp',1)[0];metadata={'issuer':base+'/issuer','authorization_endpoint':base+'/authorize','token_endpoint':base+'/token','pkce_s256':True};callback_manager=QNetworkAccessManager();callbacks=[];browser=[]
    def open_url(value):
        browser.append(value.toString());params=parse_qs(urlsplit(browser[0]).query)
        def send():callbacks.append(callback_manager.get(QNetworkRequest(QUrl(params['redirect_uri'][0]+'?'+urlencode({'code':'synthetic-code','state':params['state'][0]})))))
        QTimer.singleShot(0,send);return True
    job=OAuthAuthorization(url,metadata,'synthetic-client',open_url=open_url,timeout_ms=10000);loop=QEventLoop();out=[];job.finished.connect(lambda value:(out.append(value),loop.quit()));timer=QTimer();timer.setSingleShot(True);timer.timeout.connect(loop.quit);timer.start(12000);job.start();loop.exec();timer.stop()
    if not out or out[0].get('access_token')!='synthetic-access' or len(requests)!=1:raise RuntimeError('OAuth token exchange failed')
    body=parse_qs(requests[0].decode());auth=parse_qs(urlsplit(browser[0]).query);challenge=base64.urlsafe_b64encode(hashlib.sha256(body['code_verifier'][0].encode()).digest()).rstrip(b'=').decode()
    if auth['code_challenge']!=[challenge] or body['resource']!=[url] or auth['resource']!=[url]:raise RuntimeError('OAuth PKCE or resource binding failed')
    job.manager.clearConnectionCache();callback_manager.clearConnectionCache()
    return {'sdk_version':version('mcp'),'transport':'https','checks':['loopback authorization callback','state and PKCE','resource binding','verified HTTPS token exchange']}


def run_oauth_discovery(url):
    from PySide6.QtCore import QEventLoop,QTimer
    from agentnik.mcp_oauth_discovery import OAuthMetadataDiscovery
    loop=QEventLoop();out=[];job=OAuthMetadataDiscovery(url,timeout_ms=10000);job.finished.connect(lambda value:(out.append(value),loop.quit()));timer=QTimer();timer.setSingleShot(True);timer.timeout.connect(loop.quit);timer.start(12000);job.start();loop.exec();timer.stop()
    if not out or 'error' in out[0]:raise RuntimeError('OAuth metadata discovery failed')
    if out[0]['resource']['resource']!=url or not out[0]['authorization_server']['pkce_s256']:raise RuntimeError('Unexpected OAuth discovery result')
    job.manager.clearConnectionCache()
    return {'sdk_version':version('mcp'),'transport':'https','checks':['protected resource metadata','authorization server metadata','issuer and resource validation','PKCE metadata']}


def run_standalone_resume(session,resume):
    from PySide6.QtCore import QEventLoop,QTimer
    loop=QEventLoop();out={'result':None,'error':None,'notices':0,'disconnected':False}
    def maybe_done():
        if out['result'] is not None and out['notices']>=2:loop.quit()
    def discovered(info):
        tool=next((item for item in info['tool_details'] if item['name']=='reconnect_standalone'),None)
        if not tool or not session.call(tool,{}):out['error']='Unable to start synthetic tool';loop.quit()
    def progress(detail):
        if detail.startswith('MCP resources changed;'):out['notices']+=1;resume['first_notice'].set()
        if detail.startswith('MCP server event stream disconnected;'):out['disconnected']=True;resume['disconnected'].set()
        maybe_done()
    def called(value):out['result']=value;maybe_done()
    session.discovered.connect(discovered);session.progress.connect(progress);session.called.connect(called)
    session.ended.connect(lambda value:(out.update(error=value.get('error','Session ended')),loop.quit()))
    timer=QTimer();timer.setSingleShot(True);timer.timeout.connect(lambda:(out.update(error='Standalone resumption test timed out'),loop.quit()));timer.start(15000)
    session.start();loop.exec();timer.stop()
    cleanup=QEventLoop();closed=[];session.finished.connect(lambda message:(closed.append(message),cleanup.quit()));QTimer.singleShot(4000,cleanup.quit)
    if not session.closed:session.shutdown();cleanup.exec()
    session.manager.clearConnectionCache()
    if out['error']:raise RuntimeError(out['error'])
    if not out['disconnected'] or out['notices']!=2 or resume['calls']!=1 or not any(resume['gets']) or not resume['stored_before_reconnect']:raise RuntimeError('SDK standalone stream did not replay both notifications')
    if out['result']['call_result']['content'][0]['text']!='Standalone stream closed':raise RuntimeError('Unexpected synthetic tool result')
    if not closed or closed[0].get('session_closed') is not True:raise RuntimeError('HTTPS session shutdown was not confirmed')
    return {'sdk_version':version('mcp'),'transport':'https','checks':['SDK-initiated standalone stream close','resume GET with event ID','notification replay','one tool execution','session closed']}


def run_resume(session,resume):
    from PySide6.QtCore import QEventLoop,QTimer
    loop=QEventLoop();out={'result':None,'error':None,'resumed':False}
    def discovered(info):
        tool=next((item for item in info['tool_details'] if item['name']=='reconnect_tool'),None)
        if not tool or not session.call(tool,{}):out['error']='Unable to start synthetic tool';loop.quit()
    def progress(detail):
        if 'response stream disconnected' in detail:out['resumed']=True
    session.discovered.connect(discovered);session.progress.connect(progress)
    session.called.connect(lambda value:(out.update(result=value),loop.quit()))
    session.ended.connect(lambda value:(out.update(error=value.get('error','Session ended')),loop.quit()))
    timer=QTimer();timer.setSingleShot(True);timer.timeout.connect(lambda:(out.update(error='Resumption test timed out'),loop.quit()));timer.start(15000)
    session.start();loop.exec();timer.stop()
    cleanup=QEventLoop();closed=[];session.finished.connect(lambda message:(closed.append(message),cleanup.quit()));QTimer.singleShot(4000,cleanup.quit)
    if not session.closed:session.shutdown();cleanup.exec()
    session.manager.clearConnectionCache()
    if out['error']:raise RuntimeError(out['error'])
    if not out['resumed'] or resume['calls']!=1 or not any(resume['gets']):raise RuntimeError('SDK stream was not resumed without repeating the call')
    if not out['result'] or out['result']['call_result']['content'][0]['text']!='Resumed result':raise RuntimeError('Unexpected resumed tool result')
    if not closed or closed[0].get('session_closed') is not True:raise RuntimeError('HTTPS session shutdown was not confirmed')
    return {'sdk_version':version('mcp'),'transport':'https','checks':['SDK-initiated response stream close','resume GET with event ID','one tool execution','resumed result','session closed']}


def run_cancel(session,cancelled,observed):
    from PySide6.QtCore import QEventLoop,QTimer
    loop=QEventLoop();out={'started':False,'finished':None,'error':None}
    def discovered(info):
        tool=next((item for item in info['tool_details'] if item['name']=='wait_for_cancel'),None)
        if not tool or not session.call(tool,{}):out['error']='Unable to start synthetic tool';loop.quit()
    def progress(detail):
        if detail.startswith('Progress') and not out['started']:
            out['started']=True;QTimer.singleShot(0,session.shutdown)
    session.discovered.connect(discovered);session.progress.connect(progress)
    session.called.connect(lambda _: (out.update(error='Stopped call returned a result'),loop.quit()))
    session.ended.connect(lambda value:(out.update(error=value.get('error','Session ended')),loop.quit()))
    session.finished.connect(lambda value:(out.update(finished=value),loop.quit()))
    timeout=QTimer();timeout.setSingleShot(True);timeout.timeout.connect(lambda:(out.update(error='Cancellation test timed out'),loop.quit()));timeout.start(15000)
    session.start();loop.exec();timeout.stop()
    if not session.closed:session.shutdown()
    session.manager.clearConnectionCache()
    if out['error']:raise RuntimeError(out['error'])
    if not out['started'] or not out['finished'] or out['finished'].get('session_closed') is not True:raise RuntimeError('Cancellation shutdown was not confirmed')
    calls=[entry for entry in observed if entry.get('method')=='tools/call'];notifications=[entry for entry in observed if entry.get('method')=='notifications/cancelled']
    if len(calls)!=1 or len(notifications)!=1 or notifications[0].get('params',{}).get('requestId')!=calls[0].get('id'):raise RuntimeError('SDK server did not receive the matching cancellation notification')
    if not cancelled.wait(3):raise RuntimeError('SDK server did not end the synthetic operation')
    return {'sdk_version':version('mcp'),'transport':'https','checks':['notification received with matching request ID','synthetic server operation ended','session closed']}


if __name__=='__main__':
    if sys.argv[1:]==['--server']:make_server().run(transport='stdio')
    elif sys.argv[1:]==['--https']:print(json.dumps(run_https()))
    elif sys.argv[1:]==['--https-cancel']:print(json.dumps(run_https(test_cancel=True)))
    elif sys.argv[1:]==['--https-resume']:print(json.dumps(run_https(test_resume=True)))
    elif sys.argv[1:]==['--https-standalone-resume']:print(json.dumps(run_https(test_standalone_resume=True)))
    elif sys.argv[1:]==['--https-oauth-discovery']:print(json.dumps(run_https(test_oauth=True)))
    elif sys.argv[1:]==['--https-oauth-flow']:print(json.dumps(run_https(test_oauth_flow=True)))
    elif sys.argv[1:]==['--https-oauth-refresh']:print(json.dumps(run_https(test_oauth_refresh=True)))
    elif sys.argv[1:]==['--https-oauth-ui']:print(json.dumps(run_https(test_oauth_ui=True)))
    elif not sys.argv[1:]:
        from PySide6.QtCore import QCoreApplication
        from agentnik.mcp_local import LocalSession
        app=QCoreApplication.instance() or QCoreApplication([])
        print(json.dumps(run(LocalSession(sys.executable,[str(Path(__file__).resolve()),'--server'],timeout_seconds=15),'stdio')))
    else:raise SystemExit('Usage: mcp_sdk_smoke.py [--https|--https-cancel|--https-resume|--https-standalone-resume|--https-oauth-discovery|--https-oauth-flow|--https-oauth-refresh|--https-oauth-ui]')
