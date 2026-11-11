"""Bounded, asynchronous HTTP MCP discovery; no server tools are executed."""
import json
from PySide6.QtCore import QObject,QTimer,QUrl,Signal
from PySide6.QtNetwork import QNetworkAccessManager,QNetworkRequest,QNetworkReply
from .mcp_support import MAX_OUTPUT,PROTOCOL,initialize_request,parse_initialize

MAX_PAGES=5
MAX_TOOLS=100
MAX_DESCRIPTION=8000
MAX_SCHEMA=32000
MAX_DETAILS=200000

def preview_tool(item):
    """Keep bounded server-provided metadata for display, never execution."""
    description=item.get('description','');schema=item.get('inputSchema')
    if not isinstance(description,str):raise ValueError('Invalid MCP tool description')
    if schema is not None and not isinstance(schema,dict):raise ValueError('Invalid MCP input schema')
    description_bytes=description.encode('utf-8');description_clipped=len(description_bytes)>MAX_DESCRIPTION
    description=description_bytes[:MAX_DESCRIPTION].decode('utf-8','ignore')
    if schema is None:return {'description':description,'description_clipped':description_clipped,'schema':None,'schema_status':'missing'}
    encoded=json.dumps(schema,ensure_ascii=True,separators=(',',':')).encode('ascii')
    if len(encoded)>MAX_SCHEMA:return {'description':description,'description_clipped':description_clipped,'schema':None,'schema_status':'oversized'}
    return {'description':description,'description_clipped':description_clipped,'schema':schema,'schema_status':'available'}

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
    if len(found)!=1:raise ValueError('Missing or duplicate MCP response')
    return found[0]


class RemoteProbe(QObject):
    finished=Signal(object)
    def __init__(self,url,token,parent=None):
        super().__init__(parent);self.url=url;self.token=token;self.manager=QNetworkAccessManager(self);self.reply=None;self.buffer=bytearray();self.session='';self.phase='initialize';self.result=None;self.pages=0;self.names=[];self.details=[];self.detail_bytes=0;self.cursors=set()
        self.timer=QTimer(self);self.timer.setSingleShot(True);self.timer.timeout.connect(lambda:self.stop('MCP connection timed out.'))
    def start(self):
        self.timer.start(15000);self.send(initialize_request())
    def send(self,message):
        request=QNetworkRequest(QUrl(self.url));request.setAttribute(QNetworkRequest.Attribute.RedirectPolicyAttribute,QNetworkRequest.RedirectPolicy.ManualRedirectPolicy)
        request.setRawHeader(b'Content-Type',b'application/json');request.setRawHeader(b'Accept',b'application/json, text/event-stream')
        if self.token:request.setRawHeader(b'Authorization',('Bearer '+self.token).encode('ascii'))
        if self.phase!='initialize':
            request.setRawHeader(b'MCP-Protocol-Version',PROTOCOL.encode())
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
                    self.result['tools']=[];self.result['tool_details']=[];self.result['more_tools']=False;self.close_session();return
                self.phase='tools';self.pages=1;self.send({'jsonrpc':'2.0','id':2,'method':'tools/list','params':{}});return
            ctype=str(reply.header(QNetworkRequest.KnownHeaders.ContentTypeHeader) or '').split(';',1)[0].strip().lower()
            message=response_message(bytes(self.buffer),ctype,1 if self.phase=='initialize' else self.pages+1)
            if self.phase=='initialize':
                self.result=parse_initialize(json.dumps(message).encode());session=reply.rawHeader('Mcp-Session-Id')
                if not isinstance(session,str):session=bytes(session).decode('ascii')
                if len(session)>512 or any(ord(ch)<33 or ord(ch)>126 for ch in session):raise ValueError('Invalid MCP session identifier')
                self.session=session;self.phase='initialized';self.send({'jsonrpc':'2.0','method':'notifications/initialized'});return
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
            self.result['tools']=self.names[:MAX_TOOLS];self.result['tool_details']=self.details;self.result['more_tools']=bool(cursor) or len(self.names)>MAX_TOOLS;self.close_session()
        except (ValueError,UnicodeError,TypeError,RecursionError):self.stop('Invalid or unsupported MCP server response.')
    def close_session(self):
        if not self.session:self.complete(None);return
        self.phase='closing';self.timer.start(3000)
        request=QNetworkRequest(QUrl(self.url));request.setAttribute(QNetworkRequest.Attribute.RedirectPolicyAttribute,QNetworkRequest.RedirectPolicy.ManualRedirectPolicy)
        request.setRawHeader(b'MCP-Protocol-Version',PROTOCOL.encode());request.setRawHeader(b'Mcp-Session-Id',self.session.encode('ascii'))
        if self.token:request.setRawHeader(b'Authorization',('Bearer '+self.token).encode('ascii'))
        self.buffer=bytearray();self.reply=self.manager.deleteResource(request);self.reply.readyRead.connect(self.consume);self.reply.finished.connect(self.received)
    def complete(self,closed):
        self.timer.stop();self.token='';self.result['session_closed']=closed;self.finished.emit(self.result)
    def stop(self,message='MCP connection cancelled.'):
        self.timer.stop();reply=self.reply;self.reply=None
        if reply:reply.abort();reply.deleteLater()
        if self.phase=='closing' and self.result:self.complete(False);return
        self.token='';self.finished.emit({'error':message})
