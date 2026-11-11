"""Bounded, asynchronous HTTP MCP discovery and explicitly reviewed calls."""
import json
from PySide6.QtCore import QObject,QTimer,QUrl,Signal
from PySide6.QtNetwork import QNetworkAccessManager,QNetworkRequest,QNetworkReply
from .mcp_support import MAX_OUTPUT,PROTOCOL,initialize_request,parse_initialize
from .mcp_resources import ResourcePages,TemplatePages,expand_template,parse_resource_text
from .mcp_prompts import PromptPages,parse_prompt_messages,validate_prompt_arguments

HTTP_PROTOCOLS=(PROTOCOL,'2025-06-18','2025-03-26')
MAX_PAGES=5
MAX_TOOLS=100
MAX_DESCRIPTION=8000
MAX_SCHEMA=32000
MAX_DETAILS=200000

def preview_tool(item):
    """Keep bounded server-provided metadata for display, never execution."""
    description=item.get('description','');schema=item.get('inputSchema')
    execution=item.get('execution',{})
    if not isinstance(execution,dict):raise ValueError('Invalid MCP tool execution metadata')
    task_support=execution.get('taskSupport','forbidden')
    if task_support not in ('forbidden','optional','required'):raise ValueError('Unsupported MCP task execution metadata')
    if not isinstance(description,str):raise ValueError('Invalid MCP tool description')
    if schema is not None and not isinstance(schema,dict):raise ValueError('Invalid MCP input schema')
    description_bytes=description.encode('utf-8');description_clipped=len(description_bytes)>MAX_DESCRIPTION
    description=description_bytes[:MAX_DESCRIPTION].decode('utf-8','ignore')
    detail={'description':description,'description_clipped':description_clipped,'task_support':task_support}
    if 'annotations' in item:
        annotations=item['annotations']
        if not isinstance(annotations,dict):raise ValueError('Invalid MCP tool annotations')
        hints={}
        for key in ('title','readOnlyHint','destructiveHint','idempotentHint','openWorldHint'):
            if key not in annotations:continue
            value=annotations[key]
            if key=='title':
                if not isinstance(value,str) or len(value)>256 or any(ord(ch)<32 or ord(ch)==127 for ch in value):raise ValueError('Invalid MCP tool annotation')
            elif type(value) is not bool:raise ValueError('Invalid MCP tool annotation')
            hints[key]=value
        detail['annotations']=hints
    if schema is None:return dict(detail,schema=None,schema_status='missing')
    encoded=json.dumps(schema,ensure_ascii=True,separators=(',',':'),allow_nan=False).encode('ascii')
    if len(encoded)>MAX_SCHEMA:return dict(detail,schema=None,schema_status='oversized')
    return dict(detail,schema=schema,schema_status='available')


def contains_secret(value,secret):
    if isinstance(value,str):return secret in value
    if isinstance(value,list):return any(contains_secret(item,secret) for item in value)
    if isinstance(value,dict):return any(contains_secret(key,secret) or contains_secret(item,secret) for key,item in value.items())
    return False


def response_message(data,content_type,expected_id):
    if content_type=='application/json':messages=[data]
    elif content_type=='text/event-stream':
        messages=[]
        for event in data.replace(b'\r\n',b'\n').split(b'\n\n'):
            parts=[line[5:].lstrip(b' ') for line in event.split(b'\n') if line.startswith(b'data:')]
            if parts and any(parts):messages.append(b'\n'.join(parts))
    else:raise ValueError('Unsupported MCP response type')
    found=[]
    for raw in messages:
        try:message=json.loads(raw)
        except (ValueError,UnicodeError,RecursionError):raise ValueError('Invalid MCP response') from None
        if not isinstance(message,dict) or message.get('jsonrpc')!='2.0':raise ValueError('Invalid MCP response')
        if message.get('id')==expected_id and type(message.get('id')) is int:found.append(message)
        elif 'id' in message:raise ValueError('Unsupported server request or unexpected response')
        elif message.get('method') in ('notifications/tools/list_changed','notifications/resources/list_changed','notifications/prompts/list_changed'):raise ValueError('MCP server list changed')
    if len(found)!=1:raise ValueError('Missing or duplicate MCP response')
    return found[0]


class RemoteProbe(QObject):
    finished=Signal(object)
    def __init__(self,url,token,parent=None,invocation=None,expected_identity=None):
        super().__init__(parent);self.url=url;self.token=token;self.invocation=invocation;self.expected_identity=expected_identity;self.manager=QNetworkAccessManager(self);self.reply=None;self.buffer=bytearray();self.session='';self.protocol=PROTOCOL;self.phase='initialize';self.result=None;self.pages=0;self.names=[];self.details=[];self.detail_bytes=0;self.cursors=set();self.next_id=0;self.current_id=None
        self.timer=QTimer(self);self.timer.setSingleShot(True);self.timer.timeout.connect(lambda:self.stop('MCP connection timed out.'))
    def start(self):
        self.timer.start(15000);self.send(initialize_request())
    def send(self,message):
        if 'id' in message:
            self.next_id+=1;self.current_id=self.next_id;message=dict(message,id=self.current_id)
        request=QNetworkRequest(QUrl(self.url));request.setAttribute(QNetworkRequest.Attribute.RedirectPolicyAttribute,QNetworkRequest.RedirectPolicy.ManualRedirectPolicy)
        request.setRawHeader(b'Content-Type',b'application/json');request.setRawHeader(b'Accept',b'application/json, text/event-stream')
        if self.token:request.setRawHeader(b'Authorization',('Bearer '+self.token).encode('ascii'))
        if self.phase!='initialize':
            request.setRawHeader(b'MCP-Protocol-Version',self.protocol.encode())
            if self.session:request.setRawHeader(b'Mcp-Session-Id',self.session.encode('ascii'))
        self.buffer=bytearray();self.reply=self.manager.post(request,json.dumps(message).encode());self.reply.readyRead.connect(self.consume);self.reply.finished.connect(self.received)
    def consume(self):
        if not self.reply:return
        self.buffer.extend(bytes(self.reply.readAll()))
        if len(self.buffer)>MAX_OUTPUT:self.stop('MCP response exceeded the output limit.')
    def received(self):
        reply=self.reply
        if reply is None:return
        self.consume()
        if self.reply is None:return
        self.reply=None;reply.deleteLater()
        status=reply.attribute(QNetworkRequest.Attribute.HttpStatusCodeAttribute)
        if self.phase=='closing':
            self.complete(isinstance(status,int) and 200<=status<300);return
        if status not in ((202,) if self.phase=='initialized' else (200,)):
            self.stop('MCP server returned an HTTP or network error'+(' ('+str(status)+').' if isinstance(status,int) else '.'));return
        try:
            if self.token and self.token.encode('ascii') in self.buffer:raise ValueError('Credential reflected in response')
            if self.phase=='initialized':
                if 'tools' not in self.result['capabilities']:
                    if self.invocation:raise ValueError('MCP tools unavailable')
                    self.result['tools']=[];self.result['tool_details']=[];self.result['more_tools']=False;self.finish_discovery();return
                self.phase='tools';self.pages=1;self.send({'jsonrpc':'2.0','id':2,'method':'tools/list','params':{}});return
            ctype=str(reply.header(QNetworkRequest.KnownHeaders.ContentTypeHeader) or '').split(';',1)[0].strip().lower()
            message=response_message(bytes(self.buffer),ctype,self.current_id)
            if self.token and contains_secret(message,self.token):raise ValueError('Credential reflected in response')
            if self.phase=='initialize':
                self.result=parse_initialize(json.dumps(message).encode(),HTTP_PROTOCOLS);self.protocol=self.result['protocol']
                if self.expected_identity and any(self.result.get(key)!=value for key,value in self.expected_identity.items()):raise ValueError('MCP server identity changed')
                session=reply.rawHeader('Mcp-Session-Id')
                if not isinstance(session,str):session=bytes(session).decode('ascii')
                if len(session)>512 or any(ord(ch)<33 or ord(ch)>126 for ch in session):raise ValueError('Invalid MCP session identifier')
                self.session=session;self.phase='initialized';self.send({'jsonrpc':'2.0','method':'notifications/initialized'});return
            if self.phase in ('prompt_list','prompt_get'):
                outcome=message.get('result')
                if not isinstance(outcome,dict):raise ValueError('Invalid MCP prompt response')
                if self.phase=='prompt_list':
                    cursor,outcome=self.prompt_pages.accept(outcome)
                    if cursor:self.prompt_list_page(cursor);return
                    self.prompt_items=outcome['prompts']
                    if self.prompt_invocation:
                        expected=self.prompt_invocation['prompt'];current=next((x for x in self.prompt_items if x['name']==expected['name']),None)
                        if current!=expected:self.stop('MCP prompt definition changed.');return
                        args=self.prompt_invocation['arguments'];self.prompt_invocation=None;self.phase='prompt_get'
                        self.send({'jsonrpc':'2.0','id':0,'method':'prompts/get','params':{'name':current['name'],'arguments':args}});return
                else:outcome=parse_prompt_messages(outcome)
                self.timer.stop();self.phase='ready';self.prompts.emit(outcome);return
            if self.phase in ('resource_list','resource_read','template_list'):
                outcome=message.get('result')
                if not isinstance(outcome,dict):raise ValueError('Invalid MCP resource response')
                if self.phase=='template_list':
                    cursor,outcome=self.template_pages.accept(outcome)
                    if cursor:self.template_list_page(cursor);return
                    self.template_items=outcome['templates']
                elif self.phase=='resource_list':
                    cursor,outcome=self.resource_pages.accept(outcome)
                    if cursor:self.resource_list_page(cursor);return
                    self.resource_items=outcome['resources']
                else:outcome=parse_resource_text(outcome,self.resource_uri)
                self.timer.stop();self.phase='ready';self.resources.emit(outcome);return
            if self.phase=='call':
                outcome=message.get('result')
                if not isinstance(outcome,dict) or not isinstance(outcome.get('content'),list) or ('isError' in outcome and type(outcome['isError']) is not bool):raise ValueError('Invalid MCP tool result')
                self.result['call_result']=outcome;self.finish_call();return
            result=message.get('result');tools=result.get('tools') if isinstance(result,dict) else None
            if not isinstance(tools,list) or len(tools)>MAX_TOOLS:raise ValueError('Invalid MCP tool list')
            for item in tools:
                name=item.get('name') if isinstance(item,dict) else None
                if not isinstance(name,str) or not name or len(name)>128 or any(ord(ch)<32 or ord(ch)==127 for ch in name):raise ValueError('Invalid MCP tool name')
                if name in self.names:raise ValueError('Duplicate MCP tool name')
                self.names.append(name)
                if len(self.details)<MAX_TOOLS:
                    detail=preview_tool(item);detail['name']=name
                    size=len(json.dumps(detail,ensure_ascii=True).encode('ascii'))
                    if self.detail_bytes+size>MAX_DETAILS:detail={'name':name,'description':'','description_clipped':True,'schema':None,'schema_status':'details budget exceeded'};size=len(json.dumps(detail).encode())
                    self.detail_bytes+=size;self.details.append(detail)
            cursor=result.get('nextCursor')
            if cursor is not None:
                if not isinstance(cursor,str) or not cursor or len(cursor)>1024 or cursor in self.cursors:raise ValueError('Invalid MCP cursor')
                self.cursors.add(cursor)
            if cursor and self.pages<MAX_PAGES and len(self.names)<MAX_TOOLS:
                self.pages+=1;self.send({'jsonrpc':'2.0','id':self.pages+1,'method':'tools/list','params':{'cursor':cursor}});return
            self.result['tools']=self.names[:MAX_TOOLS];self.result['tool_details']=self.details;self.result['more_tools']=bool(cursor) or len(self.names)>MAX_TOOLS
            if self.invocation:
                expected=self.invocation['tool'];current=next((item for item in self.details if item['name']==expected['name']),None)
                if current!=expected or current.get('schema_status')!='available' or current.get('task_support')=='required':
                    self.stop('MCP tool definition changed; test the server again before calling.');return
                args=self.invocation['arguments'];payload=json.dumps(args,ensure_ascii=False,allow_nan=False)
                if not isinstance(args,dict) or len(payload.encode())>16000 or (self.token and self.token in payload):raise ValueError('Invalid MCP tool arguments')
                self.phase='call';self.send({'jsonrpc':'2.0','id':self.pages+2,'method':'tools/call','params':{'name':current['name'],'arguments':args}});return
            self.finish_discovery()
        except (ValueError,UnicodeError,TypeError,RecursionError):self.stop('Invalid or unsupported MCP server response.')
    def finish_discovery(self):
        self.close_session()
    def finish_call(self):
        self.close_session()
    def close_session(self):
        if not self.session:self.complete(None);return
        self.phase='closing';self.timer.start(3000)
        request=QNetworkRequest(QUrl(self.url));request.setAttribute(QNetworkRequest.Attribute.RedirectPolicyAttribute,QNetworkRequest.RedirectPolicy.ManualRedirectPolicy)
        request.setRawHeader(b'MCP-Protocol-Version',self.protocol.encode());request.setRawHeader(b'Mcp-Session-Id',self.session.encode('ascii'))
        if self.token:request.setRawHeader(b'Authorization',('Bearer '+self.token).encode('ascii'))
        self.buffer=bytearray();self.reply=self.manager.deleteResource(request);self.reply.readyRead.connect(self.consume);self.reply.finished.connect(self.received)
    def complete(self,closed):
        self.timer.stop();self.token='';self.result['session_closed']=closed;self.finished.emit(self.result)
    def stop(self,message='MCP connection cancelled.'):
        self.timer.stop();reply=self.reply;self.reply=None
        if reply:reply.abort();reply.deleteLater()
        if self.phase=='closing' and self.result:self.complete(False);return
        self.token='';self.finished.emit({'error':message,'call_uncertain':self.phase=='call'})


class RemoteSession(RemoteProbe):
    """One bounded Streamable HTTP session shared by a coding run."""
    discovered=Signal(object)
    called=Signal(object)
    ended=Signal(object)
    resources=Signal(object)
    prompts=Signal(object)

    def __init__(self,url,token,parent=None):
        super().__init__(url,token,parent)
        self.closed=False

    def finish_discovery(self):
        self.timer.stop();self.phase='ready'
        self.discovered.emit(dict(self.result,session_stateful=bool(self.session)))

    def finish_call(self):
        outcome=self.result.pop('call_result')
        self.timer.stop();self.phase='ready';self.invocation=None
        self.called.emit({'call_result':outcome})

    def call(self,tool,arguments):
        if self.closed or self.phase!='ready':return False
        self.invocation={'tool':tool,'arguments':arguments}
        self.pages=1;self.names=[];self.details=[];self.detail_bytes=0;self.cursors=set()
        self.phase='tools';self.timer.start(15000)
        self.send({'jsonrpc':'2.0','id':2,'method':'tools/list','params':{}})
        return True

    def list_resources(self):
        if self.closed or self.phase!='ready' or 'resources' not in self.result['capabilities']:return False
        self.resource_items=[];self.resource_pages=ResourcePages();self.phase='resource_list';self.timer.start(15000)
        self.resource_list_page(None);return True

    def resource_list_page(self,cursor):
        self.send({'jsonrpc':'2.0','id':0,'method':'resources/list','params':{'cursor':cursor} if cursor else {}})

    def read_resource(self,uri):
        if self.closed or self.phase!='ready' or uri not in [item['uri'] for item in getattr(self,'resource_items',[])]:return False
        if self.token and self.token in uri:return False
        self.resource_uri=uri;self.phase='resource_read';self.timer.start(15000)
        self.send({'jsonrpc':'2.0','id':0,'method':'resources/read','params':{'uri':uri}});return True

    def list_resource_templates(self):
        if self.closed or self.phase!='ready' or 'resources' not in self.result['capabilities']:return False
        self.template_items=[];self.template_pages=TemplatePages();self.phase='template_list';self.timer.start(15000)
        self.template_list_page(None);return True

    def template_list_page(self,cursor):
        self.send({'jsonrpc':'2.0','id':0,'method':'resources/templates/list','params':{'cursor':cursor} if cursor else {}})

    def read_resource_template(self,template,arguments,uri):
        if self.closed or self.phase!='ready' or template not in getattr(self,'template_items',[]) or not template['supported']:return False
        try:
            if expand_template(template['uriTemplate'],arguments)!=uri or (self.token and (contains_secret(arguments,self.token) or self.token in uri)):return False
        except (ValueError,UnicodeError):return False
        self.resource_uri=uri;self.phase='resource_read';self.timer.start(15000)
        self.send({'jsonrpc':'2.0','id':0,'method':'resources/read','params':{'uri':uri}});return True

    def list_prompts(self,invocation=None):
        if self.closed or self.phase!='ready' or 'prompts' not in self.result['capabilities']:return False
        if invocation:
            if invocation['prompt'] not in getattr(self,'prompt_items',[]):return False
            try:
                validate_prompt_arguments(invocation['prompt'],invocation['arguments'])
                if self.token and contains_secret(invocation['arguments'],self.token):return False
            except (ValueError,UnicodeError,RecursionError):return False
        self.prompt_invocation=invocation;self.prompt_items=[];self.prompt_pages=PromptPages();self.phase='prompt_list';self.timer.start(15000)
        self.prompt_list_page(None);return True

    def prompt_list_page(self,cursor):
        self.send({'jsonrpc':'2.0','id':0,'method':'prompts/list','params':{'cursor':cursor} if cursor else {}})

    def shutdown(self):
        if self.closed:return
        self.closed=True;self.timer.stop()
        reply=self.reply;self.reply=None
        if reply:reply.abort();reply.deleteLater()
        if self.session:
            self.close_session()
        else:
            self.token='';self.finished.emit({'session_closed':None})

    def complete(self,closed):
        self.timer.stop();self.token='';self.finished.emit({'session_closed':closed})

    def stop(self,message='MCP connection cancelled.'):
        if self.phase=='closing':
            super().stop(message);return
        uncertain=self.phase=='call'
        self.ended.emit({'error':message,'call_uncertain':uncertain})
        self.shutdown()
