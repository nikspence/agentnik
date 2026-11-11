"""Bounded, asynchronous HTTP MCP discovery; no server tools are executed."""
import json
from PySide6.QtCore import QObject,QTimer,QUrl,Signal
from PySide6.QtNetwork import QNetworkAccessManager,QNetworkRequest,QNetworkReply
from .mcp_support import MAX_OUTPUT,PROTOCOL,initialize_request,parse_initialize


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
        super().__init__(parent);self.url=url;self.token=token;self.manager=QNetworkAccessManager(self);self.reply=None;self.buffer=bytearray();self.session='';self.phase='initialize';self.result=None
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
        if status not in ((202,) if self.phase=='initialized' else (200,)):
            self.stop('MCP server returned an HTTP or network error'+(' ('+str(status)+').' if isinstance(status,int) else '.'));return
        try:
            if self.token and self.token.encode('ascii') in self.buffer:raise ValueError('Credential reflected in response')
            if self.phase=='initialized':
                if 'tools' not in self.result['capabilities']:
                    self.result['tools']=[];self.result['more_tools']=False;self.timer.stop();self.token='';self.finished.emit(self.result);return
                self.phase='tools';self.send({'jsonrpc':'2.0','id':2,'method':'tools/list','params':{}});return
            ctype=str(reply.header(QNetworkRequest.KnownHeaders.ContentTypeHeader) or '').split(';',1)[0].strip().lower()
            message=response_message(bytes(self.buffer),ctype,1 if self.phase=='initialize' else 2)
            if self.phase=='initialize':
                self.result=parse_initialize(json.dumps(message).encode());session=reply.rawHeader('Mcp-Session-Id')
                if not isinstance(session,str):session=bytes(session).decode('ascii')
                if len(session)>512 or any(ord(ch)<33 or ord(ch)>126 for ch in session):raise ValueError('Invalid MCP session identifier')
                self.session=session;self.phase='initialized';self.send({'jsonrpc':'2.0','method':'notifications/initialized'});return
            result=message.get('result');tools=result.get('tools') if isinstance(result,dict) else None
            if not isinstance(tools,list) or len(tools)>100:raise ValueError('Invalid MCP tool list')
            names=[]
            for item in tools:
                name=item.get('name') if isinstance(item,dict) else None
                if not isinstance(name,str) or not name or len(name)>128 or any(ord(ch)<32 or ord(ch)==127 for ch in name):raise ValueError('Invalid MCP tool name')
                names.append(name)
            self.result['tools']=names;self.result['more_tools']=bool(result.get('nextCursor'));self.timer.stop();self.token='';self.finished.emit(self.result)
        except (ValueError,UnicodeError,TypeError,RecursionError):self.stop('Invalid or unsupported MCP server response.')
    def stop(self,message='MCP connection cancelled.'):
        self.timer.stop();reply=self.reply;self.reply=None
        if reply:reply.abort();reply.deleteLater()
        self.token='';self.finished.emit({'error':message})
