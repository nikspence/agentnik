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


def make_server(cancelled=None):
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


def run_https(test_cancel=False):
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

    app=QCoreApplication.instance() or QCoreApplication([])
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
        cancelled=threading.Event();observed=[]
        sdk_app=make_server(cancelled if test_cancel else None).streamable_http_app()
        async def monitored_app(scope,receive,send):
            chunks=[]
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
            await sdk_app(scope,monitored_receive,send)
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
            session=RemoteSession('https://127.0.0.1:'+str(port)+'/mcp','',timeout_seconds=15)
            result=run_cancel(session,cancelled,observed) if test_cancel else run(session,'https')
            result['tls_probe_version']=negotiated
        finally:
            server.should_exit=True;thread.join(10);listener.close();QSslConfiguration.setDefaultConfiguration(original)
            if thread.is_alive():raise RuntimeError('Local HTTPS server did not stop')
    return result


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
    elif not sys.argv[1:]:
        from PySide6.QtCore import QCoreApplication
        from agentnik.mcp_local import LocalSession
        app=QCoreApplication.instance() or QCoreApplication([])
        print(json.dumps(run(LocalSession(sys.executable,[str(Path(__file__).resolve()),'--server'],timeout_seconds=15),'stdio')))
    else:raise SystemExit('Usage: mcp_sdk_smoke.py [--https|--https-cancel]')
